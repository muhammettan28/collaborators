// The worker pdf.js draws the Slides tab's pages in (SlidesView): its own
// worker, imported so that the build bundles it (a URL to it isn't allowed
// for an ESM package). Once loaded in a worker, it answers on its own.
import 'pdfjs-dist/build/pdf.worker.min.mjs';
