/**
 * Unit tests for Debussy Dashboard JavaScript functions.
 * Uses jsdom to test critical DOM rendering functions.
 * Run with: node tests/test_dashboard.js
 */

const { JSDOM } = require('jsdom');
const assert = require('assert');

// Mock DOM setup
const dom = new JSDOM(`
  <!DOCTYPE html>
  <html>
  <body>
    <div id="gnd-r" style="display:none">
      <table><tbody id="gnd-body"></tbody></table>
    </div>
    <div id="geonames-r" style="display:none">
      <table><tbody id="geonames-body"></tbody></table>
    </div>
  </body>
  </html>
`);

const window = dom.window;
const document = window.document;

// Expose global functions
global.document = document;

// Utility functions from dashboard
const $ = (id) => document.getElementById(id);
const esc = (str) => {
  if (!str) return '';
  const el = document.createElement('div');
  el.textContent = str;
  return el.innerHTML;
};

// Dashboard render functions under test
function renderGeoNamesResults(r) {
  if ($('geonames-r')) $('geonames-r').style.display = 'block';
  const results = r.results || [];
  $('geonames-body').innerHTML = results.map(gr => {
    const tm = gr.top_match;
    let coords = '';
    if (tm && (tm.lat || tm.lng)) {
      const lat = Number(tm.lat).toFixed(4), lng = Number(tm.lng).toFixed(4);
      coords = '<a href="https://www.openstreetmap.org/?mlat=' + lat + '&mlon=' + lng + '#map=10/' + lat + '/' + lng + '" target="_blank" rel="noopener" style="font-size:.68rem">' + lat + ', ' + lng + '</a>';
    }
    return '<tr>' +
      '<td style="font-weight:600">' + esc(gr.text || '') + '</td>' +
      '<td><span class="etype etype-' + esc(gr.type || 'LOC') + '">' + esc(gr.type || '') + '</span></td>' +
      '<td>' + (tm ? '<a class="gnd-match" href="' + esc(tm.uri || '') + '" target="_blank" rel="noopener">' + esc(tm.geonames_id) + '</a>' : '<span class="gnd-none">—</span>') + '</td>' +
      '<td>' + (tm ? esc(tm.name || '') : '') + '</td>' +
      '<td style="font-size:.68rem">' + (tm ? esc(tm.country || '') : '') + '</td>' +
      '<td>' + coords + '</td>' +
      '</tr>';
  }).join('');
}

function renderGNDResults(r) {
  if ($('gnd-r')) $('gnd-r').style.display = 'block';
  const results = r.results || [];
  $('gnd-body').innerHTML = results.map(gr => {
    const tm = gr.top_match;
    return '<tr>' +
      '<td style="font-weight:600">' + esc(gr.text || '') + '</td>' +
      '<td><span class="etype etype-' + esc(gr.type || 'CON') + '">' + esc(gr.type || '') + '</span></td>' +
      '<td>' + (tm ? '<code class="gnd-match">' + esc(tm.gnd_id) + '</code>' : '<span class="gnd-none">—</span>') + '</td>' +
      '<td>' + (tm ? esc(tm.preferred_name) : '') + '</td>' +
      '<td style="font-size:.68rem">' + (tm ? esc(tm.type || '') : '') + '</td>' +
      '<td style="font-size:.68rem">' + (tm ? (tm.alternative_names || []).slice(0, 2).map(n => esc(n)).join(', ') : '') + '</td>' +
      '</tr>';
  }).join('');
}

// ============= TESTS =============

let testsPassed = 0;
let testsFailed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`✓ ${name}`);
    testsPassed++;
  } catch (e) {
    console.error(`✗ ${name}: ${e.message}`);
    testsFailed++;
  }
}

// Test: renderGeoNamesResults with mock data
test('renderGeoNamesResults renders single result', () => {
  const mockData = {
    results: [{
      text: 'Berlin',
      type: 'LOC',
      top_match: {
        geonames_id: '2950159',
        name: 'Berlin',
        country: 'Germany',
        lat: 52.5200,
        lng: 13.4050,
        uri: 'https://www.geonames.org/2950159'
      }
    }]
  };

  renderGeoNamesResults(mockData);
  const body = $('geonames-body');
  assert(body.innerHTML.includes('Berlin'), 'Should contain "Berlin"');
  assert(body.innerHTML.includes('2950159'), 'Should contain GeoNames ID');
  assert(body.innerHTML.includes('Germany'), 'Should contain country');
  assert(body.innerHTML.includes('52.5200'), 'Should contain latitude');
  assert(body.innerHTML.includes('13.4050'), 'Should contain longitude');
});

test('renderGeoNamesResults handles missing top_match', () => {
  const mockData = {
    results: [{
      text: 'UnknownPlace',
      type: 'LOC',
      top_match: null
    }]
  };

  renderGeoNamesResults(mockData);
  const body = $('geonames-body');
  assert(body.innerHTML.includes('UnknownPlace'), 'Should contain search term');
  assert(body.innerHTML.includes('gnd-none'), 'Should show empty marker');
  assert(!body.innerHTML.includes('2950159'), 'Should not have GeoNames ID');
});

test('renderGeoNamesResults handles multiple results', () => {
  const mockData = {
    results: [
      {
        text: 'Berlin',
        type: 'LOC',
        top_match: { geonames_id: '2950159', name: 'Berlin', country: 'Germany', uri: 'https://www.geonames.org/2950159' }
      },
      {
        text: 'Paris',
        type: 'LOC',
        top_match: { geonames_id: '2988507', name: 'Paris', country: 'France', uri: 'https://www.geonames.org/2988507' }
      }
    ]
  };

  renderGeoNamesResults(mockData);
  const body = $('geonames-body');
  const rows = body.querySelectorAll('tr');
  assert.strictEqual(rows.length, 2, 'Should have 2 rows');
  assert(body.innerHTML.includes('Berlin'), 'Should contain Berlin');
  assert(body.innerHTML.includes('Paris'), 'Should contain Paris');
});

test('renderGNDResults renders single result', () => {
  const mockData = {
    results: [{
      text: 'Goethe',
      type: 'PER',
      top_match: {
        gnd_id: '118540238',
        preferred_name: 'Goethe, Johann Wolfgang von',
        type: 'Person',
        alternative_names: ['Goethe, J. W. von', 'Göthe']
      }
    }]
  };

  renderGNDResults(mockData);
  const body = $('gnd-body');
  assert(body.innerHTML.includes('Goethe'), 'Should contain "Goethe"');
  assert(body.innerHTML.includes('118540238'), 'Should contain GND ID');
  assert(body.innerHTML.includes('Goethe, Johann Wolfgang von'), 'Should contain preferred name');
  assert(body.innerHTML.includes('Person'), 'Should contain type');
});

test('renderGNDResults handles missing top_match', () => {
  const mockData = {
    results: [{
      text: 'UnknownPerson',
      type: 'PER',
      top_match: null
    }]
  };

  renderGNDResults(mockData);
  const body = $('gnd-body');
  assert(body.innerHTML.includes('UnknownPerson'), 'Should contain search term');
  assert(body.innerHTML.includes('gnd-none'), 'Should show empty marker');
  assert(!body.innerHTML.includes('118540238'), 'Should not have GND ID');
});

test('renderGNDResults escapes HTML in names', () => {
  const mockData = {
    results: [{
      text: '<script>alert("xss")</script>',
      type: 'PER',
      top_match: {
        gnd_id: '123456',
        preferred_name: 'Test <Name>',
        type: 'Person',
        alternative_names: []
      }
    }]
  };

  renderGNDResults(mockData);
  const body = $('gnd-body');
  assert(!body.innerHTML.includes('<script>'), 'Should not contain script tags');
  assert(body.innerHTML.includes('&lt;script&gt;'), 'Should escape HTML entities');
  assert(body.innerHTML.includes('&lt;Name&gt;'), 'Should escape angle brackets in name');
});

test('renderGeoNamesResults escapes HTML in names', () => {
  const mockData = {
    results: [{
      text: '<img src=x>',
      type: 'LOC',
      top_match: {
        geonames_id: '123',
        name: 'Test <Place>',
        country: 'Country & Region',
        uri: 'https://example.com'
      }
    }]
  };

  renderGeoNamesResults(mockData);
  const body = $('geonames-body');
  assert(!body.innerHTML.includes('<img src=x>'), 'Should not contain img tags');
  assert(body.innerHTML.includes('&lt;img src=x&gt;'), 'Should escape HTML in text');
  assert(body.innerHTML.includes('&lt;Place&gt;'), 'Should escape HTML in place name');
  assert(body.innerHTML.includes('Country &amp; Region'), 'Should escape ampersand');
});

test('renderGNDResults handles empty results', () => {
  const mockData = { results: [] };
  renderGNDResults(mockData);
  const body = $('gnd-body');
  assert.strictEqual(body.innerHTML, '', 'Should have empty HTML for empty results');
});

test('renderGeoNamesResults handles empty results', () => {
  const mockData = { results: [] };
  renderGeoNamesResults(mockData);
  const body = $('geonames-body');
  assert.strictEqual(body.innerHTML, '', 'Should have empty HTML for empty results');
});

// Report results
console.log(`\n${testsPassed} tests passed, ${testsFailed} tests failed`);
process.exit(testsFailed > 0 ? 1 : 0);
