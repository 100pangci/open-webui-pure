<script lang="ts">
	import Computer from '$lib/components/icons/Computer.svelte';
	import Database from '$lib/components/icons/Database.svelte';
	import Link from '$lib/components/icons/Link.svelte';
	import Lock from '$lib/components/icons/Lock.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import SettingsAlt from '$lib/components/icons/SettingsAlt.svelte';
	import User from '$lib/components/layout/Sidebar/icons/User.svelte';

	export let id: string;
	export let className = 'size-3.5';
	export let strokeWidth = '2';
</script>

{#if id === 'users'}
	<User {className} {strokeWidth} />
{:else if id === 'groups'}
	<svg
		aria-hidden="true"
		xmlns="http://www.w3.org/2000/svg"
		fill="none"
		viewBox="0 0 24 24"
		stroke="currentColor"
		stroke-width={strokeWidth}
		class={className}
	>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z"
		/>
	</svg>
{:else if id === 'general'}
	<SettingsAlt {className} {strokeWidth} />
{:else if id === 'authentication'}
	<Lock {className} {strokeWidth} />
{:else if id === 'connections'}
	<Link {className} {strokeWidth} />
{:else if id === 'models'}
	<svg
		aria-hidden="true"
		xmlns="http://www.w3.org/2000/svg"
		fill="none"
		viewBox="0 0 24 24"
		stroke="currentColor"
		stroke-width={strokeWidth}
		class={className}
	>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			d="M4 7.5C4 5.57 7.58 4 12 4s8 1.57 8 3.5S16.42 11 12 11 4 9.43 4 7.5Z"
		/>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			d="M4 7.5v4C4 13.43 7.58 15 12 15s8-1.57 8-3.5v-4"
		/>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			d="M4 11.5v4C4 17.43 7.58 19 12 19s8-1.57 8-3.5v-4"
		/>
	</svg>
{:else if id === 'interface'}
	<Computer {className} {strokeWidth} />
{:else if id === 'images'}
	<Photo {className} {strokeWidth} />
{:else if id === 'db'}
	<Database {className} {strokeWidth} />
{/if}
