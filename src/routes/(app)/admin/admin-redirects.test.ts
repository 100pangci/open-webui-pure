import { describe, expect, it, vi } from 'vitest';

const { redirectMock } = vi.hoisted(() => ({ redirectMock: vi.fn() }));

vi.mock('@sveltejs/kit', () => ({
	redirect: (status: number, location: string) => {
		redirectMock(status, location);
		throw new Error(`REDIRECT:${status}:${location}`);
	}
}));

const runLoad = async (load: unknown, input: unknown = {}) => {
	try {
		await (load as (input: unknown) => unknown)(input);
	} catch (error) {
		return error as Error;
	}

	throw new Error('load() did not redirect');
};

const redirectedUrl = (error: Error) => {
	const match = error.message.match(/^REDIRECT:(\d+):(.*)$/);
	expect(match).not.toBeNull();
	return {
		status: Number(match![1]),
		url: new URL(match![2], 'http://localhost')
	};
};

describe('legacy /admin redirects', () => {
	it('redirects /admin to the Users settings tab', async () => {
		const { load } = await import('./+page');

		const { status, url } = redirectedUrl(await runLoad(load));
		expect(status).toBe(307);
		expect(url.pathname).toBe('/');
		expect(url.searchParams.get('settings')).toBe('admin:users');
	});

	it('redirects /admin/users to the Users settings tab', async () => {
		const { load } = await import('./users/+page');

		const { url } = redirectedUrl(await runLoad(load));
		expect(url.searchParams.get('settings')).toBe('admin:users');
	});

	it.each([
		['overview', 'admin:users'],
		['groups', 'admin:groups']
	])('redirects /admin/users/%s to %s', async (tab, expected) => {
		const { load } = await import('./users/[tab]/+page');

		const { url } = redirectedUrl(
			await runLoad(load, {
				params: { tab },
				url: new URL(`http://localhost/admin/users/${tab}?id=abc123`)
			})
		);
		expect(url.searchParams.get('settings')).toBe(expected);
		expect(url.searchParams.get('id')).toBe('abc123');
	});

	it('redirects /admin/settings to the General settings tab', async () => {
		const { load } = await import('./settings/+page');

		const { url } = redirectedUrl(
			await runLoad(load, { url: new URL('http://localhost/admin/settings') })
		);
		expect(url.searchParams.get('settings')).toBe('admin:general');
	});

	it('redirects /admin/settings/<tab> to the matching settings tab', async () => {
		const { load } = await import('./settings/[tab]/+page');

		const { url } = redirectedUrl(
			await runLoad(load, {
				params: { tab: 'models' },
				url: new URL('http://localhost/admin/settings/models')
			})
		);
		expect(url.searchParams.get('settings')).toBe('admin:models');
	});

	it('keeps unknown admin user tabs on the Users settings tab', async () => {
		const { load } = await import('./users/[tab]/+page');

		const { url } = redirectedUrl(
			await runLoad(load, {
				params: { tab: 'whatever' },
				url: new URL('http://localhost/admin/users/whatever')
			})
		);
		expect(url.searchParams.get('settings')).toBe('admin:users');
	});
});
