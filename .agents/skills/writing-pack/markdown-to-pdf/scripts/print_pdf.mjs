import { readFile } from 'node:fs/promises';

const [runtime, chrome, source, output, latinFamily, latinFile] = process.argv.slice(2);
if (!latinFamily || !latinFile) throw new Error('Pass the selected Latin font family and file.');
const fontData = (await readFile(latinFile)).toString('base64');
// Keep the preload separate from body faces that may share the same family.
const footerFamily = `Markdown Footer: ${latinFamily}`;
const fontFace = `@font-face { font-family: ${JSON.stringify(footerFamily)}; src: url("data:font/otf;base64,${fontData}"); font-weight: 400; font-style: normal; }`;
const footerTemplate = `<style>${fontFace}</style><div style="font-family:${JSON.stringify(footerFamily).replaceAll('"', '&quot;')};font-size:10px;color:#555;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>`;
const { chromium } = await import(runtime);
const browser = await chromium.launch({ executablePath: chrome, headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--allow-file-access-from-files'] });
try {
  const page = await browser.newPage();
  await page.goto(source, { waitUntil: 'load' });
  await page.emulateMedia({ media: 'print' });
  // Chromium's separate header/footer document does not wait for web fonts.
  // Preload the identical data URL in the main document before printing.
  await page.addStyleTag({ content: fontFace });
  await page.evaluate(async family => {
    await document.fonts.load(`10px ${JSON.stringify(family)}`, '0123456789 /');
  }, footerFamily);
  await page.evaluate(async () => {
    await document.fonts.ready;
    for (const face of document.fonts) {
      if (face.status === 'error') throw new Error(`Font failed to load: ${face.family}`);
    }
    await Promise.all([...document.images].map(img => img.decode()));
    // Tables taller than the available page height must be allowed to split.
    for (const table of document.querySelectorAll('table')) {
      if (table.getBoundingClientRect().height > (297 - 16 - 18) * 96 / 25.4) {
        table.classList.add('long-table');
      }
    }
  });
  await page.pdf({ path: output, format: 'A4', printBackground: true, preferCSSPageSize: true,
    margin: { top: '16mm', right: '15mm', bottom: '18mm', left: '15mm' },
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate });
} finally {
  await browser.close();
}
