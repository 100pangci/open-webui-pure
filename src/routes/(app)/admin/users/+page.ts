import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Legacy `/admin/users` bookmark → Settings → Admin → Users.
export const load: PageLoad = () => {
	throw redirect(307, `/?settings=${encodeURIComponent('admin:users')}`);
};
