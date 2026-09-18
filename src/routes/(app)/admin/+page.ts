import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Legacy `/admin` bookmark: the standalone Admin Panel no longer exists, the
// user management lives in Settings → Admin → Users.
export const load: PageLoad = () => {
	throw redirect(307, `/?settings=${encodeURIComponent('admin:users')}`);
};
