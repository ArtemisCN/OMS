#!/usr/bin/env node
/**
 * Generate a properly-oriented PDF from HTML
 * Usage: cat input.html | node generate_pdf.js [width] [height] [output_path]
 */
const puppeteer = require('puppeteer');
const fs = require('fs');

async function main() {
    const width = process.argv[2] || '140mm';
    const height = process.argv[3] || '240mm';
    const outputPath = process.argv[4] || '/dev/stdout';
    
    // Read HTML from stdin
    let html = '';
    process.stdin.setEncoding('utf-8');
    for await (const chunk of process.stdin) {
        html += chunk;
    }
    
    const browser = await puppeteer.launch({
        executablePath: '/usr/bin/chromium-browser',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
    });
    
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'networkidle0' });
    
    await page.pdf({
        path: outputPath,
        width: width,
        height: height,
        printBackground: true,
        margin: { top: '0', right: '0', bottom: '0', left: '0' }
    });
    
    await browser.close();
    console.error('PDF generated: ' + outputPath);
}

main().catch(err => {
    console.error('PDF generation failed:', err.message);
    process.exit(1);
});
