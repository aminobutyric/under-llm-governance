# Beta support

Use [GitHub Issues](https://github.com/aminobutyric/under-llm-governance/issues)
for beta bugs, installation failures, and feature requests. Before filing, try
the latest beta and include:

- `ulg --version`, Python version, Linux distribution, and installation method;
- the command run, expected result, actual exit code, and sanitized output;
- for sandbox failures, the JSON from `ulg sandbox-preflight` and rootless
  Docker version; and
- minimal reproduction steps that do not contain private source or secrets.

The beta has no support SLA. Never post credentials, proprietary code, raw
prompts, or private audit data in an issue. Report security concerns through
the private process in [SECURITY.md](SECURITY.md).
