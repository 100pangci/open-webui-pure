<script lang="ts">
	import { onMount } from 'svelte';

	import { socket, user } from '$lib/stores';

	import ChatList from './ChatList.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getSharedFolderChats } from '$lib/apis/folders';
	import { registerFolderRefreshHandler } from '$lib/stores/chatList';

	type FolderPlaceholderFolder = {
		id?: string;
		shared?: boolean;
		user_id?: string;
		access_grants?: unknown[];
	};

	type FolderChat = {
		id: string;
		active?: boolean;
		[key: string]: unknown;
	};

	export let folder: FolderPlaceholderFolder | null = null;

	const CHATS_PAGE_SIZE = 10;
	let page = 1;
	let totalChats = 0;
	let orderBy: 'title' | 'updated_at' = 'updated_at';
	let direction: 'asc' | 'desc' = 'desc';
	let currentFolderId: string | null = null;

	let chats: FolderChat[] | null = null;
	let chatListLoading = false;
	let refreshQueued = false;

	$: showOwnerInfo = Boolean(
		folder?.shared ||
		(folder?.user_id && folder.user_id !== $user?.id) ||
		(folder?.access_grants?.length ?? 0) > 0
	);

	const setSortKey = (key: 'title' | 'updated_at') => {
		if (orderBy === key) {
			direction = direction === 'asc' ? 'desc' : 'asc';
		} else {
			orderBy = key;
			direction = key === 'title' ? 'asc' : 'desc';
		}
		page = 1;
		setChatList();
	};

	const setPage = (nextPage: number) => {
		if (nextPage === page || chatListLoading) {
			return;
		}

		page = nextPage;
		setChatList();
	};

	const updateChatActive = (chatId: string, active: boolean) => {
		if (!chats) {
			return false;
		}

		let found = false;
		chats = chats.map((chat) => {
			if (chat.id !== chatId) {
				return chat;
			}
			found = true;
			return { ...chat, active };
		});
		return found;
	};

	const updateChatLastReadAt = (chatId: string, lastReadAt: number) => {
		if (!chats) {
			return false;
		}

		let found = false;
		chats = chats.map((chat) => {
			if (chat.id !== chatId) {
				return chat;
			}
			found = true;
			return { ...chat, last_read_at: lastReadAt };
		});
		return found;
	};

	const refreshChatListSoon = (resetPage = false) => {
		if (refreshQueued) {
			if (resetPage) {
				page = 1;
			}
			return;
		}
		if (resetPage) {
			page = 1;
		}
		refreshQueued = true;
		queueMicrotask(async () => {
			refreshQueued = false;
			await setChatList();
		});
	};

	const setChatList = async (clear = false) => {
		const folderId = folder?.id;
		if (clear) {
			chats = null;
		}

		if (folderId) {
			// Always use the shared folder endpoint so owners also see
			// chats created by users who have write access to this folder.
			chatListLoading = true;
			const res = await getSharedFolderChats(localStorage.token, folderId, {
				page,
				sortBy: orderBy,
				sortDir: direction
			}).catch((error) => {
				console.error(error);
				return null;
			});

			if (res && res.chats) {
				chats = res.chats;
				totalChats = res.total ?? res.chats.length;
			} else {
				chats = [];
				totalChats = 0;
			}
			chatListLoading = false;
		} else {
			chats = [];
			totalChats = 0;
			chatListLoading = false;
		}
	};

	const chatEventHandler = (event: {
		chat_id?: string;
		data?: { type?: string; data?: { active?: boolean; last_read_at?: number } };
	}) => {
		if (event.data?.type === 'chat:active' && event.chat_id) {
			const active = event.data.data?.active ?? false;
			if (!updateChatActive(event.chat_id, active) && active) {
				refreshChatListSoon(true);
			}
		} else if (event.data?.type === 'chat:list') {
			const lastReadAt = event.data.data?.last_read_at;
			if (
				event.chat_id &&
				typeof lastReadAt === 'number' &&
				updateChatLastReadAt(event.chat_id, lastReadAt)
			) {
				// The read marker clears the unread dot; reloading would reset the page.
				return;
			}
			refreshChatListSoon(true);
		}
	};

	onMount(() => {
		// undefined refreshes every folder chat list; a folder id refreshes only that one.
		const unregister = registerFolderRefreshHandler((folderId) => {
			if (folderId === undefined || folderId === folder?.id) {
				return setChatList();
			}
		});
		const socketInstance = $socket;
		socketInstance?.on('events', chatEventHandler);
		socketInstance?.on('connect', refreshChatListSoon);

		return () => {
			unregister();
			socketInstance?.off('events', chatEventHandler);
			socketInstance?.off('connect', refreshChatListSoon);
		};
	});

	$: if (folder?.id && folder.id !== currentFolderId) {
		currentFolderId = folder.id;
		page = 1;
		setChatList(true);
	}

	$: if (!folder?.id && currentFolderId !== null) {
		currentFolderId = null;
		chats = [];
		totalChats = 0;
	}
</script>

<div>
	{#if chats !== null}
		<ChatList
			{chats}
			{chatListLoading}
			{showOwnerInfo}
			{page}
			total={totalChats}
			perPage={CHATS_PAGE_SIZE}
			{orderBy}
			{direction}
			onPageChange={setPage}
			onSort={setSortKey}
		/>
	{:else}
		<div class="py-10"><Spinner /></div>
	{/if}
</div>
