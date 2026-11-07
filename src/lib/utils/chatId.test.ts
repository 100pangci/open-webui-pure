import { describe, expect, it } from 'vitest';
import { createTemporaryChatId, isSavedChatId, isTemporaryChatId } from './chatId';

describe('createTemporaryChatId', () => {
	it('binds a UUID conversation to the creating socket session', () => {
		const chatId = createTemporaryChatId('session-a');

		expect(chatId).toMatch(
			/^temporary:session-a:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
		);
		expect(isTemporaryChatId(chatId)).toBe(true);
		expect(isSavedChatId(chatId)).toBe(false);
	});

	it('creates a distinct conversation per call', () => {
		expect(createTemporaryChatId('session-a')).not.toBe(createTemporaryChatId('session-a'));
	});

	it('requires a live session', () => {
		expect(() => createTemporaryChatId(undefined)).toThrow();
	});
});

describe('temporary chat classification', () => {
	it.each(['temporary:session-a', 'temporary:session-a:conversation', 'local:session-a'])(
		'treats %s as temporary',
		(chatId) => {
			expect(isTemporaryChatId(chatId)).toBe(true);
			expect(isSavedChatId(chatId)).toBe(false);
		}
	);

	it.each(['chat-id', 'channel:session-a', '', null, undefined])(
		'does not treat %s as temporary',
		(chatId) => {
			expect(isTemporaryChatId(chatId)).toBe(false);
		}
	);

	it('only treats regular chat ids as saved', () => {
		expect(isSavedChatId('chat-id')).toBe(true);
		expect(isSavedChatId('channel:session-a')).toBe(false);
		expect(isSavedChatId(null)).toBe(false);
	});
});
