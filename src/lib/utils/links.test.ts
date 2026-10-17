import { describe, expect, it } from 'vitest';
import { safeLinkUrl } from './links';

describe('safeLinkUrl', () => {
	it.each([
		'https://example.com',
		'http://example.com',
		'mailto:user@example.com',
		'tel:+1234',
		'/api/v1/files/file-id/content',
		'./relative-file',
		'#section',
		'//example.com/image'
	])('preserves permitted links: %s', (url) => {
		expect(safeLinkUrl(url)).toBe(url);
	});

	it.each([
		'javascript:alert(1)',
		' JAVASCRIPT:alert(1)',
		'java\nscript:alert(1)',
		'data:text/html,<script>alert(1)</script>',
		'vbscript:msgbox(1)',
		'file:///etc/passwd',
		'http://[',
		'',
		null,
		undefined,
		{}
	])('rejects unsafe or malformed links: %s', (url) => {
		expect(safeLinkUrl(url)).toBeUndefined();
	});
});
