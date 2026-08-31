#!/usr/bin/env node
'use strict';

// predc's entry point.
//
// gren-tvision ships a `gren-tui` bin that runs any compiled Gren program, and
// for the examples that is the right thing: they are demonstrations, and the
// name on the command line is the runtime's. An application is not a
// demonstration. `predc` is the name the user types, the path to the compiled
// module is ours and not theirs, and it is resolved against this file rather
// than the working directory -- a tool you carry every day gets run from
// wherever you happen to be standing.
//
// It is also where the host port will be wired when the time tool needs
// Intl: `run()` hands back the Gren app, so ports beyond the two the runtime
// insists on are the launcher's to subscribe to.

const path = require('path');

const run = require('gren-tvision');

const compiled = path.join(__dirname, '..', 'main.js');

let main;
try {
  main = require(compiled);
} catch (err) {
  if (err.code !== 'MODULE_NOT_FOUND') throw err;
  console.error('predc: not built yet -- run ./build.sh');
  process.exit(2);
}

run(main);
