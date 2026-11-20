<script lang="ts">
	import { navigating, page } from '$app/state';

	import Chat from '$lib/components/chat/Chat.svelte';

	// While a chat-to-chat navigation is in flight, page.params still holds the old id.
	const params = $derived(
		(navigating.to?.route.id === page.route.id && navigating.to.params) || page.params
	);
</script>

<Chat chatIdProp={params.id} />
