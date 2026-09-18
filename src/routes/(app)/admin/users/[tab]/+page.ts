import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Legacy `/admin/users/<tab>` links. `overview` maps to the Users settings tab,
// `groups` to the Groups settings tab (preserving `?id=` deep links).
export const load: PageLoad = ({ params, url }) => {
	const searchParams = new URLSearchParams(url.searchParams);
	searchParams.set('settings', params.tab === 'groups' ? 'admin:groups' : 'admin:users');

	throw redirect(307, `/?${searchParams.toString()}`);
};
