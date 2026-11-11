// Loader for the editor tests in Node: pdf.js (loaded from the server's static
// folder in the browser) is replaced by an empty module.
import { register } from 'node:module';
register('./hooks.mjs', import.meta.url);
