import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const api = vi.hoisted(() => ({
	chats: [] as Array<{ id: string; title: string; updated_at: number; created_at: number }>,
	pinned: [] as Array<{ id: string; title: string; updated_at: number; created_at: number }>,
	getChatList: vi.fn(),
	getPinnedChatList: vi.fn()
}));

vi.mock('$lib/apis/chats', () => ({
	getChatList: api.getChatList,
	getPinnedChatList: api.getPinnedChatList
}));

import {
	CHAT_LIST_PAGE_SIZE,
	chats,
	pinnedChats,
	loadNextChatListPage,
	reconcileChatListPage,
	refreshChatList,
	removeChatFromList,
	resetChatListState
} from './chatList';

type TestChat = { id: string; title: string; updated_at: number; created_at: number };

const makeChats = (count: number, newestAt = 1_000_000): TestChat[] =>
	Array.from({ length: count }, (_, index) => ({
		id: `chat-${String(index).padStart(4, '0')}`,
		title: `Chat ${index}`,
		updated_at: newestAt - index,
		created_at: newestAt - index
	}));

const pageSlice = (items: TestChat[], page: number) =>
	items.slice((page - 1) * CHAT_LIST_PAGE_SIZE, page * CHAT_LIST_PAGE_SIZE);

const ids = (items: Array<{ id: string }> | null) => (items ?? []).map((chat) => chat.id);

const deferred = <T>() => {
	let resolve!: (value: T) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
};

describe('chatList store pagination', () => {
	beforeEach(() => {
		resetChatListState();
		api.chats = makeChats(250);
		api.pinned = [];
		api.getChatList.mockReset();
		api.getPinnedChatList.mockReset();
		api.getChatList.mockImplementation(async (_token: string, page: number) =>
			pageSlice(api.chats, page)
		);
		api.getPinnedChatList.mockImplementation(async () => api.pinned);
	});

	it('loads pages 1-3, reconciles the current page after a delete and continues with page 4 without gaps or duplicates', async () => {
		const first = await refreshChatList('token');
		expect(first.accepted).toBe(true);
		expect(ids(get(chats))).toEqual(ids(api.chats.slice(0, 60)));

		await loadNextChatListPage('token');
		await loadNextChatListPage('token');
		expect(get(chats)).toHaveLength(3 * CHAT_LIST_PAGE_SIZE);

		// Delete a chat on page 2, both server-side and locally.
		const deletedId = api.chats[70].id;
		api.chats = api.chats.filter((chat) => chat.id !== deletedId);

		const removal = removeChatFromList(deletedId);
		expect(removal.removedFromChats).toBe(true);
		expect(get(chats)).toHaveLength(3 * CHAT_LIST_PAGE_SIZE - 1);
		expect(ids(get(chats))).not.toContain(deletedId);

		// Reconcile refetches the last loaded page (page 3) and backfills the
		// chat that shifted up from page 4.
		const reconciled = await reconcileChatListPage('token');
		expect(reconciled.accepted).toBe(true);
		expect(reconciled.allLoaded).toBe(false);
		expect(get(chats)).toHaveLength(3 * CHAT_LIST_PAGE_SIZE);
		expect(ids(get(chats))).toEqual(ids(api.chats.slice(0, 3 * CHAT_LIST_PAGE_SIZE)));
		expect(new Set(ids(get(chats))).size).toBe(get(chats)!.length);

		// Continue paginating: page 4 must neither skip nor duplicate.
		await loadNextChatListPage('token');
		expect(get(chats)).toHaveLength(4 * CHAT_LIST_PAGE_SIZE);
		expect(ids(get(chats))).toEqual(ids(api.chats.slice(0, 4 * CHAT_LIST_PAGE_SIZE)));
		expect(ids(get(chats))).not.toContain(deletedId);
		expect(new Set(ids(get(chats))).size).toBe(get(chats)!.length);
	});

	it('keeps the loaded range contiguous when a page load races the reconcile', async () => {
		await refreshChatList('token');
		await loadNextChatListPage('token');
		await loadNextChatListPage('token');

		const deletedId = api.chats[70].id;
		api.chats = api.chats.filter((chat) => chat.id !== deletedId);
		removeChatFromList(deletedId);

		// Delay the reconcile request until the next page has already been appended.
		const pendingPage = deferred<TestChat[]>();
		api.getChatList.mockImplementationOnce(() => pendingPage.promise);

		const reconcile = reconcileChatListPage('token');
		await loadNextChatListPage('token');

		pendingPage.resolve(pageSlice(api.chats, 3));
		await reconcile;

		expect(get(chats)).toHaveLength(4 * CHAT_LIST_PAGE_SIZE);
		expect(ids(get(chats))).toEqual(ids(api.chats.slice(0, 4 * CHAT_LIST_PAGE_SIZE)));
		expect(new Set(ids(get(chats))).size).toBe(get(chats)!.length);
	});

	it('marks the list as fully loaded when reconciling the last partial page', async () => {
		api.chats = makeChats(150);

		await refreshChatList('token');
		await loadNextChatListPage('token');
		await loadNextChatListPage('token');
		expect(get(chats)).toHaveLength(150);

		// Remove a chat from page 1, then reconcile the tail page (page 3).
		const deletedId = api.chats[5].id;
		api.chats = api.chats.filter((chat) => chat.id !== deletedId);
		removeChatFromList(deletedId);

		const reconciled = await reconcileChatListPage('token');
		expect(reconciled.accepted).toBe(true);
		expect(reconciled.allLoaded).toBe(true);
		expect(ids(get(chats))).toEqual(ids(api.chats));
	});

	it('is a no-op when everything is already loaded', async () => {
		api.chats = makeChats(20);
		await refreshChatList('token');
		// One extra fetch returns an empty page, which marks the list as fully loaded.
		await loadNextChatListPage('token');

		const deletedId = api.chats[0].id;
		api.chats = api.chats.filter((chat) => chat.id !== deletedId);
		removeChatFromList(deletedId);

		const before = api.getChatList.mock.calls.length;
		const result = await reconcileChatListPage('token');

		expect(result.accepted).toBe(false);
		expect(api.getChatList.mock.calls.length).toBe(before);
		expect(ids(get(chats))).toEqual(ids(api.chats));
	});

	it('backfills page 1 after a delete so the next page does not skip a chat', async () => {
		api.chats = makeChats(100);

		await refreshChatList('token');
		expect(get(chats)).toHaveLength(CHAT_LIST_PAGE_SIZE);

		const deletedId = api.chats[0].id;
		api.chats = api.chats.filter((chat) => chat.id !== deletedId);
		removeChatFromList(deletedId);

		const reconciled = await reconcileChatListPage('token');
		expect(reconciled.accepted).toBe(true);
		expect(get(chats)).toHaveLength(CHAT_LIST_PAGE_SIZE);
		expect(ids(get(chats))).toEqual(ids(api.chats.slice(0, CHAT_LIST_PAGE_SIZE)));

		// Page 2 must start exactly where page 1 ends.
		await loadNextChatListPage('token');
		expect(ids(get(chats))).toEqual(ids(api.chats));
		expect(new Set(ids(get(chats))).size).toBe(99);
	});

	it('stays contiguous across repeated deletes and page loads', async () => {
		api.chats = makeChats(400);

		await refreshChatList('token');
		await loadNextChatListPage('token');

		const removeLoadedChatAt = async (position: number) => {
			const id = get(chats)![position].id;
			api.chats = api.chats.filter((chat) => chat.id !== id);
			removeChatFromList(id);
			await reconcileChatListPage('token');
		};

		await removeLoadedChatAt(5);
		await removeLoadedChatAt(70);
		await loadNextChatListPage('token');
		await removeLoadedChatAt(150);
		await removeLoadedChatAt(0);
		await loadNextChatListPage('token');

		const loaded = get(chats)!;
		expect(loaded).toHaveLength(4 * CHAT_LIST_PAGE_SIZE);
		expect(ids(loaded)).toEqual(ids(api.chats.slice(0, loaded.length)));
		expect(new Set(ids(loaded)).size).toBe(loaded.length);
	});

	it('removes a pinned chat locally without refetching the main list', async () => {
		// Pinned chats are not part of the main (unpinned) list, mirroring the backend.
		api.pinned = [
			{ id: 'pin-0000', title: 'Pinned 0', updated_at: 2_000_000, created_at: 2_000_000 },
			{ id: 'pin-0001', title: 'Pinned 1', updated_at: 1_999_999, created_at: 1_999_999 },
			{ id: 'pin-0002', title: 'Pinned 2', updated_at: 1_999_998, created_at: 1_999_998 }
		];
		await refreshChatList('token', { refreshPinned: true });
		expect(get(pinnedChats)).toHaveLength(3);

		const pinnedId = api.pinned[1].id;
		api.pinned = api.pinned.filter((chat) => chat.id !== pinnedId);

		const before = api.getChatList.mock.calls.length;
		const removal = removeChatFromList(pinnedId);

		expect(removal.removedFromPinned).toBe(true);
		expect(removal.removedFromChats).toBe(false);
		expect(ids(get(pinnedChats))).not.toContain(pinnedId);
		expect(api.getChatList.mock.calls.length).toBe(before);
	});
});
