import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Legacy `/admin/settings/<tab>` bookmark → Settings → Admin → <tab>.
export const load: PageLoad = ({ params, url }) => {
	const searchParams = new URLSearchParams(url.searchParams);
	searchParams.set('settings', `admin:${params.tab}`);

	throw redirect(307, `/?${searchParams.toString()}`);
};
