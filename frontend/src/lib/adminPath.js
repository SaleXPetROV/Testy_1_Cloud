// Obscure, non-guessable admin panel path (defence-in-depth on top of the
// server-side JWT + is_admin checks that actually protect every /api/admin
// route). The old predictable "/admin" URL is intentionally dead-ended to a
// redirect so scanners/curious users find nothing there.
//
// Override per deployment with REACT_APP_ADMIN_PATH (must be URL-safe). Keeping
// the real path only in your own env means it isn't advertised publicly.
const raw = (process.env.REACT_APP_ADMIN_PATH || '/gc-nogwwlhhqhvg').trim();
export const ADMIN_PATH = raw.startsWith('/') ? raw : `/${raw}`;
