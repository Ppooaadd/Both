/**
 * Upload flow: presigned POST (API) -> direct multipart upload to object storage
 * (with progress) -> project creation that starts the pipeline.
 */
import { api } from "./client";
import { ProjectCreated, UploadCreated, type ArrangementParams } from "./schemas";

export const ACCEPTED_TYPES: Record<string, string> = {
  "audio/mpeg": ".mp3",
  "audio/mp3": ".mp3",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/wave": ".wav",
  "audio/mp4": ".m4a",
  "audio/x-m4a": ".m4a",
  "audio/aac": ".aac",
  "audio/flac": ".flac",
  "audio/x-flac": ".flac",
  "audio/ogg": ".ogg",
  "audio/opus": ".opus",
  "audio/webm": ".webm",
  "audio/aiff": ".aiff",
  "audio/x-aiff": ".aiff",
  "audio/x-ms-wma": ".wma",
};
export const ACCEPT_ATTR =
  ".mp3,.wav,.m4a,.aac,.flac,.ogg,.oga,.opus,.webm,.aif,.aiff,.wma," +
  "audio/mpeg,audio/wav,audio/mp4,audio/x-m4a,audio/flac,audio/ogg,audio/opus,audio/webm,audio/aiff";
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const FORMATS_LABEL = "MP3 · WAV · M4A · FLAC · OGG · OPUS · AIFF · WMA";

const EXT_MIME: Record<string, string> = {
  mp3: "audio/mpeg",
  wav: "audio/wav",
  m4a: "audio/mp4",
  aac: "audio/aac",
  flac: "audio/flac",
  ogg: "audio/ogg",
  oga: "audio/ogg",
  opus: "audio/opus",
  webm: "audio/webm",
  aif: "audio/aiff",
  aiff: "audio/aiff",
  wma: "audio/x-ms-wma",
};

/** Browsers report inconsistent MIME types (or none) for audio; fall back to the extension. */
export function resolveMime(file: File): string | null {
  if (file.type && file.type in ACCEPTED_TYPES) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXT_MIME[ext] ?? null;
}

export function validateFile(file: File): string | null {
  if (!resolveMime(file)) return `${FORMATS_LABEL} 파일을 업로드할 수 있습니다.`;
  if (file.size === 0) return "빈 파일입니다.";
  if (file.size > MAX_UPLOAD_BYTES) return "파일 크기는 최대 100MB까지 업로드할 수 있습니다.";
  return null;
}

export function postToStorage(
  url: string,
  fields: Record<string, string>,
  file: File,
  contentType: string,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [k, v] of Object.entries(fields)) form.append(k, v);
    // S3 requires the file to be the last field.
    form.append("file", new Blob([file], { type: contentType }), file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(`파일 저장소 업로드에 실패했습니다 (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new Error("파일 저장소에 연결할 수 없습니다."));
    xhr.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

export type UploadPhase = "signing" | "uploading" | "starting";

export async function uploadAndCreateProject(
  file: File,
  params: ArrangementParams,
  onProgress: (phase: UploadPhase, fraction: number) => void,
  signal?: AbortSignal,
) {
  const mime = resolveMime(file);
  if (!mime) throw new Error("지원하지 않는 파일 형식입니다.");
  onProgress("signing", 0);
  const slot = await api("/uploads", UploadCreated, {
    method: "POST",
    body: { filename: file.name, size_bytes: file.size, mime_type: mime },
    signal,
  });
  await postToStorage(slot.url, slot.fields, file, mime, (f) => onProgress("uploading", f), signal);
  onProgress("starting", 1);
  return api("/projects", ProjectCreated, {
    method: "POST",
    body: { upload_id: slot.upload_id, params },
    signal,
  });
}
