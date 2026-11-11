export async function resolve(specifier, context, next) {
  if (specifier.endsWith('pdf.min.mjs')) {
    return { url: 'data:text/javascript,export const GlobalWorkerOptions = {}; export const getDocument = () => {}; export default {};', shortCircuit: true };
  }
  return next(specifier, context);
}
