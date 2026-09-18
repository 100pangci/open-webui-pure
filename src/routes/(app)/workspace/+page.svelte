<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { user } from '$lib/stores';

	onMount(() => {
		if ($user?.role === 'admin' || $user?.permissions?.workspace?.models) {
			goto('/workspace/models', { replaceState: true });
		} else if ($user?.permissions?.workspace?.prompts) {
			goto('/workspace/prompts', { replaceState: true });
		} else {
			goto('/', { replaceState: true });
		}
	});
</script>
