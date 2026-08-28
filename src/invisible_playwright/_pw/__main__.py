# Copyright (c) Microsoft Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The command line of the forked client - which no longer runs anything.

⛔ IT USED TO SHELL OUT TO THE NODE DRIVER, and exposed exactly one subcommand
of it: `show-trace`, the trace viewer. Everything else was refused on purpose,
because a driver CLI is a development surface and this package exists to drive a
browser, not to develop on top of one. The fork already hardwired `debugMode()`
to "" elsewhere, and this door bypassed that.

⛔ THE DRIVER WAS REMOVED ON 2026-08-28, so `show-trace` went with it: the
viewer is a Node application and there is no Node here any more. Nothing else
was lost, and the one thing that was is smaller than it looks - tracing is
outside this package's perimeter and its dispatchers refuse it by name, so
`show-trace` could only ever open a trace some other tool had produced.

What remains is a message. A command that used to work and now silently does
nothing is worse than one that says what happened.
"""

import sys


def main() -> None:
    print(
        "invisible-playwright has no command line.\n"
        "\n"
        "It used to expose one subcommand of the Node driver, `show-trace`, and "
        "the driver was removed on 2026-08-28: the browser is now driven by an "
        "in-process Python server, and nothing here downloads or runs node.\n"
        "\n"
        "To automate, use the Python API:\n"
        "    from invisible_playwright import InvisiblePlaywright\n"
        "\n"
        "To view a Playwright trace, use Playwright's own viewer - this package "
        "does not produce traces (tracing is outside its perimeter and its "
        "dispatchers refuse it by name).",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
