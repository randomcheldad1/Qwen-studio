# Qwen Studio Community — alpha

A native Ubuntu desktop workspace for local Ollama Qwen models, guarded file tools, and manual SFTP transfers. This is a sanitized public starter extracted from an existing application. It is not affiliated with Alibaba/Qwen, OpenAI, or Anthropic.

## Features

- Local Qwen chat with real file tool calls and results, separate workspaces, text attachments and saved local history.
- Completed-answer display and coordinated auto-follow, with pause and Jump to latest.
- Read/search/create/edit within the selected workspace; existing-file replacement requires a fresh hash and local diff approval. Credential paths and recognized secrets are blocked; symlinks and hardlinks are rejected.
- Manual SFTP tab: password/key/agent authentication, host-key verification, local/remote lists, verified uploads/downloads, overwrite approval and cancellation. Passwords are not saved.
- Isolated scratch Python/JavaScript execution on Linux using bubblewrap and the user systemd service. No unrestricted fallback.
- Optional local MCP server for OpenCode and an optional ComfyUI integration (configure COMFYUI_ROOT and COMFYUI_PYTHON). Image models are not included.

## Install on Ubuntu

Install Python 3, venv support, Ollama, and optionally Node.js for MCP. Then:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull qwen3:1.7b
./launch.sh
```

For scratch code execution install bubblewrap and ensure your user systemd session is available. For desktop leader control install xdotool, wmctrl, xprop, xclip and pyatspi, and use a Python environment with the system accessibility bindings. Existing signed-in ChatGPT/Claude desktop apps and an installed local vision model are required. Never put provider credentials into a model prompt.

## Manual SFTP

Open SFTP, enter your actual SSH/SFTP server details and remote root, then Connect. Verify a new host fingerprint with your provider before accepting it. Select one local file to upload or one remote file to download. Files are limited to 64 MB. Existing remote files require approval; local downloads never overwrite. Atomic remote overwrites require the server posix-rename extension. The server and its filesystem administrators must be trusted. A dropped connection may prevent temporary-file cleanup. This panel does not run remote shell commands.

## MCP for OpenCode

```sh
cd mcp-server
npm install
opencode mcp add qwen-studio -- node /absolute/path/to/qwen-studio/mcp-server/local.mjs
opencode mcp list
```

The private stdio server exposes guarded project file tools and installed-Qwen model listing. It is not a hosting connection. An optional OAuth server is provided as source only; it requires your own private configuration and HTTPS origin. No password, tunnel, or production account is bundled.

## Experimental / unavailable features

Desktop leader automation is experimental: automatic copied-reply retrieval has not passed a complete live test. Both chats can be queued, and an explicit Use copied reply action provides manual recovery into a hidden inbox. Window detection and unit tests do not prove automated chat access. Do not rely on it unattended.

Account-specific website deployment is intentionally not included. Hosting buttons report that no account is configured. Use manual SFTP with your own server or implement a reviewed publishing adapter. The example workspace is not a live website. The original user's site, publisher IDs, browser/cookie experiments, credentials, histories and generated assets are excluded. Theme Builder dependencies/assets are not bundled; the optional button may report unavailable.

## Tests and limits

Real localhost SSH/SFTP protocol tests verify upload/download, host keys, authentication rejection, confinement and overwrite checks. The Qt SFTP panel test performs actual Connect/Upload/Download button actions against a disposable server. Run from this directory:

```sh
.venv/bin/python -m unittest discover -s tests -p test_sftp_integration.py -v
.venv/bin/python -m unittest discover -s tests -p test_sftp_panel.py -v
```

Other focused file/chat tests are included. The project is alpha; a historical combined same-process Qt suite crashed, while focused modules passed. Model behavior, server configuration and desktop UI changes can still cause failures. Secret filters do not identify every possible secret: keep credentials out of workspaces.

## License

MIT for this application code. Third-party dependencies retain their own licenses; dependencies are installed separately and are not vendored in this source package.
