# Shared files and optional Feishu attachments

The communication medium and artifact storage can differ. Base requests, directory entries, and replies travel through Feishu independently of NAS. Leave files on NAS only when shared access is confirmed. If access is unknown or unavailable, use Feishu attachments or an accessible cloud link, not a sender-local path.

## Prefer confirmed shared paths

Include paths and purposes in request `context` or response `result`, using fields appropriate to the work:

```json
{"answer":"The file contains the full analysis; the table contains itemized evidence.","artifacts":[
  {"path":"/mnt/team/research/request-123/report.md","description":"Complete analysis"},
  {"path":"/mnt/team/research/request-123/evidence.csv","description":"Itemized evidence"}
]}
```

If mount paths differ, supply a shared-directory identity and relative path for the recipient to resolve locally. A sender's temporary local path is not shared storage. Use request-specific artifact locations to avoid overwrites, and retain files until the recipient has consumed them. Reading a result record does not mean its referenced files were read. The platform does not delete NAS artifacts.

## Optional native Feishu attachments

When NAS is inaccessible to the recipient or a cloud copy is wanted, reuse authenticated `lark-cli` rather than writing an uploader. Upload from the file's directory and download from the destination directory; CLI file arguments are relative to the working directory:

```sh
lark-cli base +record-upload-attachment --base-token BASE_TOKEN --table-id TABLE_ID --record-id RECORD_ID --field-id FIELD_ID --file ./report.pdf
lark-cli docs +media-download --token FILE_TOKEN --output ./report.pdf
```

`FIELD_ID` may also be an attachment field name; get `FILE_TOKEN` from the record attachment's `file_token`. Pass attachment location, token, and purpose in the request/result. The recipient uses their own Feishu identity. Put business artifacts in business records, separate from platform-managed communication versions. Follow local CLI help/errors for permissions or command differences; do not add communication preflights.

The platform separately handles oversized inline messages: Base messages over 90000 UTF-16 units are stored as attachments and read back completely. It does not collect files named by paths or replace the preference for confirmed shared references.
