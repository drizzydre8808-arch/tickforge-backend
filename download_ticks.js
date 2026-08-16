#!/usr/bin/env node
/**
 * TickForge tick downloader — uses dukascopy-node
 * Usage: node download_ticks.js <SYMBOL> <YYYY-MM-DD> <YYYY-MM-DD> <output.csv>
 *
 * Install: cd C:\tickforge-data && npm install dukascopy-node
 */

const { getHistoricalRates } = require('dukascopy-node');
const fs = require('fs');

const [,, symbol, dtFrom, dtTo, outFile] = process.argv;

if (!symbol || !dtFrom || !dtTo || !outFile) {
  console.error('Usage: node download_ticks.js SYMBOL YYYY-MM-DD YYYY-MM-DD output.csv');
  process.exit(1);
}

// Dukascopy instrument IDs (lowercase)
const INSTRUMENTS = {
  XAUUSD: 'xauusd', XAGUSD: 'xagusd',
  EURUSD: 'eurusd', GBPUSD: 'gbpusd', USDJPY: 'usdjpy',
  USDCHF: 'usdchf', AUDUSD: 'audusd', USDCAD: 'usdcad',
  NZDUSD: 'nzdusd', EURGBP: 'eurgbp', EURJPY: 'eurjpy',
  GBPJPY: 'gbpjpy', BTCUSD: 'btcusd', ETHUSD: 'ethusd',
};

const sym = symbol.toUpperCase();
const instrument = INSTRUMENTS[sym] || sym.toLowerCase();

(async () => {
  try {
    console.log(`[dukascopy] downloading ${sym} (${instrument}) ${dtFrom} → ${dtTo}`);

    const data = await getHistoricalRates({
      instrument,
      dates: { from: new Date(dtFrom), to: new Date(dtTo) },
      timeframe: 'tick',
      format: 'array',
      batchSize: 10,
      pauseBetweenBatchesMs: 200,
    });

    console.log(`[dukascopy] ${data.length} ticks received, writing CSV...`);

    const out = fs.createWriteStream(outFile);
    out.write('symbol,timestamp,bid,ask\n');
    for (const tick of data) {
      const [ts, bid, ask] = tick;
      out.write(`${sym},${new Date(ts).toISOString()},${bid},${ask}\n`);
    }
    out.end(() => {
      console.log(`[dukascopy] done — ${data.length} ticks saved to ${outFile}`);
      process.exit(0);
    });

  } catch (err) {
    console.error('[dukascopy] failed:', err.message);
    process.exit(1);
  }
})();
