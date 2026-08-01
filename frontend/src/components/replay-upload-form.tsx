"use client";

import { useEffect, useId, useRef, useState } from "react";

import type { Messages } from "@/i18n/messages";

const MAX_BYTES = 4 * 1024 * 1024 * 1024;
const ALLOWED_EXTENSIONS = new Set(["mp4", "webm", "mov"]);
const ALLOWED_MIME_TYPES = new Set(["video/mp4", "video/webm", "video/quicktime"]);

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

function formatVideoClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function validateReplayFile(file: File, messages: Messages): string | null {
  const extension = file.name.includes(".")
    ? file.name.slice(file.name.lastIndexOf(".") + 1).toLowerCase()
    : "";
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    return messages.replayFileInvalidType;
  }
  if (file.type && !ALLOWED_MIME_TYPES.has(file.type)) {
    return messages.replayFileInvalidType;
  }
  if (file.size > MAX_BYTES) {
    return messages.replayFileTooLarge;
  }
  return null;
}

export type ReplayUploadSubmit = {
  file: File;
  gameTimeZeroMs: number;
};

export function ReplayUploadForm({
  messages,
  disabled,
  onSubmit,
}: {
  messages: Messages;
  disabled?: boolean;
  onSubmit: (input: ReplayUploadSubmit) => void;
}) {
  const fileInputId = useId();
  const rightsId = useId();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [gameTimeZeroMs, setGameTimeZeroMs] = useState<number | null>(null);
  const [rightsAttested, setRightsAttested] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [anchorConfirm, setAnchorConfirm] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  function replacePreview(nextFile: File | null) {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    if (!nextFile) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(nextFile);
    objectUrlRef.current = url;
    setPreviewUrl(url);
  }

  function handleFileChange(nextFile: File | null) {
    setLocalError(null);
    setGameTimeZeroMs(null);
    setAnchorConfirm(null);
    setRightsAttested(false);
    if (!nextFile) {
      setFile(null);
      replacePreview(null);
      return;
    }
    const validationError = validateReplayFile(nextFile, messages);
    if (validationError) {
      setFile(null);
      replacePreview(null);
      setLocalError(validationError);
      return;
    }
    setFile(nextFile);
    replacePreview(nextFile);
  }

  function handleSetGameZero() {
    const video = videoRef.current;
    if (!video) return;
    const ms = Math.round(video.currentTime * 1000);
    setGameTimeZeroMs(ms);
    setAnchorConfirm(
      fill(messages.replayGameZeroConfirm, { time: formatVideoClock(video.currentTime) }),
    );
  }

  const canUpload =
    !disabled && file !== null && gameTimeZeroMs !== null && rightsAttested && localError === null;

  return (
    <form
      className="replay-upload-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!file || gameTimeZeroMs === null || !rightsAttested) return;
        onSubmit({ file, gameTimeZeroMs });
      }}
    >
      <label className="replay-file-label" htmlFor={fileInputId}>
        <span>{messages.replayFileLabel}</span>
        <input
          id={fileInputId}
          type="file"
          accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov"
          disabled={disabled}
          onChange={(event) => {
            handleFileChange(event.target.files?.[0] ?? null);
          }}
        />
      </label>

      {previewUrl ? (
        <video
          ref={videoRef}
          className="replay-video-preview"
          data-testid="replay-video-preview"
          src={previewUrl}
          controls
          playsInline
          preload="metadata"
        />
      ) : null}

      <div className="replay-anchor-controls">
        <button
          type="button"
          disabled={disabled || !file}
          onClick={handleSetGameZero}
        >
          {messages.replaySetGameZero}
        </button>
        {anchorConfirm ? <p className="replay-anchor-confirm">{anchorConfirm}</p> : null}
      </div>

      <div className="replay-rights">
        <input
          id={rightsId}
          type="checkbox"
          checked={rightsAttested}
          disabled={disabled}
          onChange={(event) => setRightsAttested(event.target.checked)}
        />
        <label htmlFor={rightsId}>{messages.replayRightsLabel}</label>
      </div>

      {localError ? (
        <p className="replay-local-error" role="alert">
          {localError}
        </p>
      ) : null}

      <button type="submit" disabled={!canUpload}>
        {messages.replayUpload}
      </button>
    </form>
  );
}
