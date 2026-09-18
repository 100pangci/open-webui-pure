import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Legacy `/admin/settings` bookmark → Settings → Admin → General.
export const load: PageLoad = ({ url }) => {
	const searchParams = new URLSearchParams(url.searchParams);
	searchParams.set('settings', 'admin:general');

	throw redirect(307, `/?${searchParams.toString()}`);
};
