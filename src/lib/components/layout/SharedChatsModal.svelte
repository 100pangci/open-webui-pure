<script lang="ts">
	import type { Writable } from 'svelte/store';
	import { toast } from 'svelte-sonner';
	import { getContext, onDestroy } from 'svelte';
	import { unshareAllChats, deleteSharedChatById, getSharedChatList } from '$lib/apis/chats';

	import ChatsModal from './ChatsModal.svelte';
	import UnshareAllConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '../common/Spinner.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let show = false;
	export let onUpdate = () => {};

	let loading = false;
	let chatList: any[] | null = null;
	let page = 1;

	let query = '';
	let orderBy = 'updated_at';
	let direction = 'desc';

	let allChatsLoaded = false;
	let chatListLoading = false;
	let searchDebounceTimeout: ReturnType<typeof setTimeout>;
	let searchController: AbortController | null = null;

	let showUnshareAllConfirmDialog = false;

	let filter: any = {};
	$: filter = {
		...(query ? { query } : {}),
		...(orderBy ? { order_by: orderBy } : {}),
		...(direction ? { direction } : {})
	};

	const cancelSearch = () => {
		searchController?.abort();
		searchController = null;
		clearTimeout(searchDebounceTimeout);
	};

	const searchHandler = async () => {
		cancelSearch();
		if (!show) return;

		const controller = new AbortController();
		searchController = controller;
		const { signal } = controller;
		page = 1;
		chatList = null;
		chatListLoading = false;

		const loadChats = async () => {
			try {
				const res = await getSharedChatList(localStorage.token, page, filter, signal);
				if (signal.aborted || searchController !== controller) return;
				chatList = res ?? [];
				allChatsLoaded = (res ?? []).length === 0;
			} catch (error) {
				if (!signal.aborted && searchController === controller) {
					toast.error(`${error}`);
					chatList = [];
					allChatsLoaded = true;
				}
			}
		};

		if (query === '') {
			await loadChats();
		} else {
			searchDebounceTimeout = setTimeout(loadChats, 500);
		}
	};

	const loadMoreChats = async () => {
		const controller = searchController;
		if (
			chatListLoading ||
			!chatList ||
			allChatsLoaded ||
			!controller ||
			controller.signal.aborted
		) {
			return;
		}

		chatListLoading = true;
		const nextPage = page + 1;

		try {
			const newChatList = await getSharedChatList(
				localStorage.token,
				nextPage,
				filter,
				controller.signal
			);
			if (controller.signal.aborted || searchController !== controller) return;
			// Advance only once the page arrived, so a failed load can be retried.
			page = nextPage;

			const results = newChatList ?? [];
			allChatsLoaded = results.length === 0;
			if (results.length > 0) {
				chatList = [...chatList, ...results];
			}
		} catch (error) {
			if (!controller.signal.aborted && searchController === controller) {
				toast.error(`${error}`);
			}
		} finally {
			if (searchController === controller) {
				chatListLoading = false;
			}
		}
	};

	const unshareHandler = async (chatId: string) => {
		const res = await deleteSharedChatById(localStorage.token, chatId).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res === true) {
			toast.success($i18n.t('Chat unshared successfully.'));
			onUpdate();
			searchHandler();
		} else if (res === false) {
			toast.error($i18n.t('Failed to unshare chat.'));
		}
	};

	const unshareAllHandler = async () => {
		loading = true;
		try {
			await unshareAllChats(localStorage.token);
			toast.success($i18n.t('All shared chats have been unshared.'));
			onUpdate();
			await searchHandler();
		} catch (error) {
			toast.error(`${error}`);
		} finally {
			loading = false;
		}
	};

	$: if (show && filter) {
		searchHandler();
	} else {
		cancelSearch();
	}

	onDestroy(cancelSearch);
</script>

<UnshareAllConfirmDialog
	bind:show={showUnshareAllConfirmDialog}
	message={$i18n.t(
		'Are you sure you want to unshare all shared chats? This will remove all share links.'
	)}
	confirmLabel={$i18n.t('Unshare All')}
	on:confirm={() => {
		unshareAllHandler();
	}}
/>

<ChatsModal
	bind:show
	bind:query
	bind:orderBy
	bind:direction
	title={$i18n.t('Shared Chats')}
	emptyPlaceholder={$i18n.t('You have no shared conversations.')}
	shareUrl={false}
	{chatList}
	{allChatsLoaded}
	{chatListLoading}
	onUpdate={() => {
		onUpdate();
		searchHandler();
	}}
	loadHandler={loadMoreChats}
	{unshareHandler}
>
	<div slot="footer">
		<div class="flex flex-wrap text-sm font-normal gap-1.5 mt-2 m-1 justify-end w-full">
			<button
				class=" px-3.5 py-1.5 font-normal hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-100 dark:outline-gray-800 rounded-3xl"
				disabled={loading}
				on:click={() => {
					showUnshareAllConfirmDialog = true;
				}}
			>
				{#if loading}
					<Spinner className="size-4" />
				{:else}
					{$i18n.t('Unshare All Shared Chats')}
				{/if}
			</button>
		</div>
	</div>
</ChatsModal>
