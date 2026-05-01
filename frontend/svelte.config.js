import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// Phase 0 ships self-hosted (no Vercel/Cloudflare/Netlify). adapter-node
		// emits a `build/` directory runnable as `node build/`. The 9.2 BFF
		// (`+server.ts` proxies to daprd) requires a server-side adapter.
		adapter: adapter()
	}
};

export default config;
