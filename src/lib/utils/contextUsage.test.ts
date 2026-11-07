import { describe, expect, it } from 'vitest';
import {
	captureUsageCheckpoint,
	estimateMessagesTokens,
	estimateTokens,
	estimateUsageGrowth
} from './contextUsage';

describe('estimateTokens', () => {
	it.each([null, undefined, ''])('returns zero for empty values: %s', (value) => {
		expect(estimateTokens(value)).toBe(0);
	});

	it('estimates four characters per token with a floor of one', () => {
		expect(estimateTokens('a')).toBe(1);
		expect(estimateTokens('abcd')).toBe(1);
		expect(estimateTokens('a'.repeat(400))).toBe(100);
	});

	it('serializes values before estimating', () => {
		expect(estimateTokens({ key: 'value' })).toBe(estimateTokens(JSON.stringify({ key: 'value' })));
	});
});

describe('estimateMessagesTokens', () => {
	it('counts message overhead and content', () => {
		expect(estimateMessagesTokens([{ content: 'a'.repeat(400) }])).toBe(104);
	});

	it('uses structured output instead of content and tool calls', () => {
		const output = [{ type: 'message', content: [{ type: 'output_text', text: 'a'.repeat(400) }] }];
		const message = { content: 'a'.repeat(40_000), tool_calls: 'a'.repeat(40_000), output };

		expect(estimateMessagesTokens([message])).toBe(4 + estimateTokens(output));
	});

	it('does not count base64 image payloads', () => {
		const message = {
			content: 'hi',
			files: [
				{ type: 'image', url: `data:image/png;base64,${'A'.repeat(100_000)}` },
				{ type: 'file', url: '/api/v1/files/file-id/content' }
			]
		};

		expect(estimateMessagesTokens([message])).toBeLessThan(50);
	});
});

describe('estimateUsageGrowth', () => {
	it('returns zero without a usage checkpoint', () => {
		expect(estimateUsageGrowth({ content: 'a'.repeat(400) })).toBe(0);
	});

	it('returns growth since the captured checkpoint', () => {
		const usage = {};
		const message = { content: 'a'.repeat(400), usage };

		captureUsageCheckpoint(message);
		expect(estimateUsageGrowth(message)).toBe(0);

		message.content += 'b'.repeat(400);
		expect(estimateUsageGrowth(message)).toBe(100);
	});

	it('anchors loaded chats on first use and reports no growth', () => {
		const usage = {};
		const message = { content: 'a'.repeat(400), usage };

		expect(estimateUsageGrowth(message)).toBe(0);

		message.content += 'b'.repeat(400);
		expect(estimateUsageGrowth(message)).toBe(100);
	});
});
