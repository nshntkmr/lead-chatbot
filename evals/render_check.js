// Formats chart values with the app's own formatter (cut out of static/app.js) and prints what the user would
// see, so the offline checks can test the rendered text and not only the numbers behind it.
// Usage: node evals/render_check.js   → JSON on stdout
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8').replace(/\r\n/g, '\n');
const body = src.match(/function fmt\(v, format = 'number', compact = false\) \{[\s\S]*?\n  \}\n/);
const pick = src.match(/const f = (b\.value_format[^;]*);/);
if (!body || !pick) {
  console.log(JSON.stringify({ error: 'fmt() or the chart format selection was not found in static/app.js' }));
  process.exit(0);
}
const fmt = new Function(body[0] + '; return fmt;')();
const formatFor = new Function('b', 'return ' + pick[1] + ';');
const show = (v, block) => fmt(v, formatFor(block));

console.log(JSON.stringify({
  new_percent_chart: show(87.35, { value_format: 'percent', percent_scale: 'percent' }),
  new_percent_small: show(0.8, { value_format: 'percent', percent_scale: 'percent' }),
  legacy_percent_chart: show(0.8735, { value_format: 'percent' }),
  currency: show(1234567, { value_format: 'currency' }),
}));
