import { get, readonly, writable } from 'svelte/store';
import { getChatList, getPinnedChatList } from '$lib/apis/chats';

export type ChatListItem = {
	id: string;
	[key: string]: unknown;
};

/**
 * Page size used by the backend chat list endpoint.  Kept here so local
 * pagination reconciliation can reason about how much of a page is filled.
 */
export const CHAT_LIST_PAGE_SIZE = 60;

const chatsStore = writable<ChatListItem[] | null>(null);
const pinnedChatsStore = writable<ChatListItem[]>([]);

export const chats = readonly(chatsStore);
export const pinnedChats = readonly(pinnedChatsStore);

let currentPage = 1;
let paginationReady = false;
let requestGeneration = 0;
let allLoaded = false;
let loadingNextPage = false;

type RefreshChatListOptions = {
	refreshPinned?: boolean;
	clearPinned?: boolean;
};

type ChatListResult = {
	accepted: boolean;
	allLoaded: boolean;
};

export const refreshChatList = async (
	token: string = '',
	options: RefreshChatListOptions = {}
): Promise<ChatListResult> => {
	const generation = ++requestGeneration;
	paginationReady = false;
	loadingNextPage = false;

	const [nextChats, nextPinnedChats] = await Promise.all([
		getChatList(token, 1) as Promise<ChatListItem[]>,
		options.refreshPinned && !options.clearPinned
			? (getPinnedChatList(token) as Promise<ChatListItem[]>)
			: Promise.resolve(undefined as ChatListItem[] | undefined)
	]);

	if (generation !== requestGeneration) {
		return { accepted: false, allLoaded };
	}

	chatsStore.set(nextChats);
	currentPage = 1;
	allLoaded = nextChats.length === 0;

	if (options.clearPinned) {
		pinnedChatsStore.set([]);
	} else if (options.refreshPinned) {
		pinnedChatsStore.set(nextPinnedChats ?? []);
	}

	paginationReady = true;
	return { accepted: true, allLoaded };
};

// The sidebar owns folder state. This bridge lets other components refresh it.
type FolderRefreshHandler = (folderId?: string | null, chat?: ChatListItem | null) => unknown;
const folderRefreshHandlers = new Set<FolderRefreshHandler>();

export const registerFolderRefreshHandler = (handler: FolderRefreshHandler) => {
	folderRefreshHandlers.add(handler);
	return () => {
		folderRefreshHandlers.delete(handler);
	};
};

export const refreshFolderChatLists = async (
	folderId?: string | null,
	chat?: ChatListItem | null
) => {
	await Promise.all([...folderRefreshHandlers].map((handler) => handler(folderId, chat)));
};

// The sidebar owns folder chat lists as well. This bridge lets delete/archive
// flows that live outside the sidebar (chat page, search modal) remove a single
// chat from every loaded folder list without resetting folder pagination.
type FolderChatRemovalHandler = (chatId: string) => unknown;
const folderChatRemovalHandlers = new Set<FolderChatRemovalHandler>();

export const registerFolderChatRemovalHandler = (handler: FolderChatRemovalHandler) => {
	folderChatRemovalHandlers.add(handler);
	return () => {
		folderChatRemovalHandlers.delete(handler);
	};
};

export const removeChatFromFolderLists = async (chatId: string) => {
	await Promise.all([...folderChatRemovalHandlers].map((handler) => handler(chatId)));
};

export const loadNextChatListPage = async (token: string = ''): Promise<ChatListResult> => {
	if (!paginationReady || allLoaded || loadingNextPage) {
		return { accepted: false, allLoaded };
	}

	const generation = requestGeneration;
	const nextPage = currentPage + 1;
	loadingNextPage = true;

	try {
		const nextChats = (await getChatList(token, nextPage)) as ChatListItem[];

		if (generation !== requestGeneration) {
			return { accepted: false, allLoaded };
		}

		allLoaded = nextChats.length === 0;
		currentPage = nextPage;

		const existingIds = new Set((get(chatsStore) ?? []).map((chat) => chat.id));
		const uniqueChats = nextChats.filter((chat) => !existingIds.has(chat.id));
		chatsStore.set([...(get(chatsStore) ?? []), ...uniqueChats]);

		return { accepted: true, allLoaded };
	} finally {
		loadingNextPage = false;
	}
};

/**
 * Mirrors the backend `chat_list_order` default sort (updated_at desc, id asc)
 * so locally merged rows keep the server order.
 */
const compareChatsByRecency = (a: ChatListItem, b: ChatListItem): number => {
	const aUpdatedAt = Number(a.updated_at ?? 0);
	const bUpdatedAt = Number(b.updated_at ?? 0);

	if (aUpdatedAt !== bUpdatedAt) {
		return bUpdatedAt - aUpdatedAt;
	}

	if (a.id === b.id) {
		return 0;
	}

	return a.id < b.id ? -1 : 1;
};

export type LocalChatRemoval = {
	removedFromChats: boolean;
	removedFromPinned: boolean;
};

/**
 * Removes a chat from the already-loaded lists (main sidebar list and pinned
 * list) without touching pagination state.  Only the single affected row
 * disappears from the DOM, so the surrounding list – and the scroll position –
 * stays intact.
 */
export const removeChatFromList = (id: string): LocalChatRemoval => {
	let removedFromChats = false;
	chatsStore.update((items) => {
		if (!items) {
			return items;
		}

		const nextItems = items.filter((chat) => chat.id !== id);
		removedFromChats = nextItems.length !== items.length;
		return removedFromChats ? nextItems : items;
	});

	let removedFromPinned = false;
	pinnedChatsStore.update((items) => {
		const nextItems = items.filter((chat) => chat.id !== id);
		removedFromPinned = nextItems.length !== items.length;
		return removedFromPinned ? nextItems : items;
	});

	return { removedFromChats, removedFromPinned };
};

/**
 * Backfills the tail of the currently loaded pages after a local removal.
 *
 * Offset pagination shifts every chat after the removed one up by one slot,
 * which means the last page that was loaded is exactly where a chat can be
 * missing.  Re-fetching `currentPage` and merging only the missing ids keeps
 * the loaded list contiguous (no duplicate, no skipped chat) without reloading
 * page 1, resetting pagination or clearing the store.
 */
export const reconcileChatListPage = async (token: string = ''): Promise<ChatListResult> => {
	if (!paginationReady || allLoaded) {
		return { accepted: false, allLoaded };
	}

	const generation = requestGeneration;
	const page = currentPage;

	const nextChats = (await getChatList(token, page)) as ChatListItem[];

	if (generation !== requestGeneration) {
		return { accepted: false, allLoaded };
	}

	const existing = get(chatsStore) ?? [];
	const existingIds = new Set(existing.map((chat) => chat.id));
	const missingChats = nextChats.filter((chat) => !existingIds.has(chat.id));

	if (missingChats.length > 0) {
		chatsStore.set([...existing, ...missingChats].sort(compareChatsByRecency));
	}

	// Only the tail page can tell us that nothing follows; a partial page that
	// is not the tail anymore (a concurrent page load advanced currentPage)
	// says nothing about subsequent pages.
	if (page === currentPage && nextChats.length < CHAT_LIST_PAGE_SIZE) {
		allLoaded = true;
	}

	return { accepted: true, allLoaded };
};

/**
 * Locally updates a chat title in both the main and pinned lists.  Renaming
 * does not change the server order, so no refetch is needed.
 */
export const updateChatTitleInList = (id: string, title: string): void => {
	const updateChat = (chat: ChatListItem) => (chat.id === id ? { ...chat, title } : chat);

	chatsStore.update((items) => (items ? items.map(updateChat) : items));
	pinnedChatsStore.update((items) => items.map(updateChat));
};

/**
 * Inserts a chat that is now the newest in the main list (e.g. a chat that was
 * just unpinned: the backend touches `updated_at`, so it belongs on top).
 */
export const addChatToList = (chat: ChatListItem): void => {
	if (!chat?.id) {
		return;
	}

	// Pin toggles touch `updated_at`/`last_read_at` server-side but the pin
	// response does not carry `last_read_at`; treat the chat as read at the
	// moment it re-entered the list.
	const listItem: ChatListItem = {
		...chat,
		last_read_at: chat.last_read_at ?? chat.updated_at ?? null
	};

	chatsStore.update((items) => {
		if (!items) {
			return items;
		}

		if (items.some((item) => item.id === listItem.id)) {
			return items.map((item) => (item.id === listItem.id ? { ...item, ...listItem } : item));
		}

		return [listItem, ...items];
	});
};

/**
 * Targeted pinned-list refresh.  Unlike `refreshChatList` this never touches
 * the main chat list or its pagination.
 */
export const refreshPinnedChats = async (token: string = ''): Promise<void> => {
	const generation = requestGeneration;
	const nextPinnedChats = (await getPinnedChatList(token)) as ChatListItem[];

	if (generation !== requestGeneration) {
		return;
	}

	pinnedChatsStore.set(nextPinnedChats);
};

export const setChatActive = (chatId: string, active: boolean): boolean => {
	let found = false;
	const updateChat = (chat: ChatListItem) => {
		if (chat.id !== chatId) {
			return chat;
		}
		found = true;
		return { ...chat, active };
	};

	chatsStore.update((items) => (items ? items.map(updateChat) : items));
	pinnedChatsStore.update((items) => items.map(updateChat));
	return found;
};

export const setChatReadAt = (chatId: string, lastReadAt: number): boolean => {
	let found = false;
	const updateChat = (chat: ChatListItem) => {
		if (chat.id !== chatId) {
			return chat;
		}
		found = true;
		return { ...chat, last_read_at: lastReadAt };
	};

	chatsStore.update((items) => (items ? items.map(updateChat) : items));
	pinnedChatsStore.update((items) => items.map(updateChat));
	return found;
};

export const setAllChatsRead = () => {
	const updateChat = (chat: ChatListItem) => ({ ...chat, last_read_at: chat.updated_at });

	chatsStore.update((items) => (items ? items.map(updateChat) : items));
	pinnedChatsStore.update((items) => items.map(updateChat));
};

export const resetChatListState = () => {
	requestGeneration += 1;
	currentPage = 1;
	paginationReady = false;
	allLoaded = false;
	loadingNextPage = false;
	chatsStore.set(null);
	pinnedChatsStore.set([]);
};
