"use client";

import { useEffect, useMemo, useState } from "react";

import { getReplayArtifactBlob } from "@/api/client";
import type { ReplayArtifact } from "@/api/schemas";
import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

export function formatGameTime(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function ArtifactImage({
  artifact,
  accessToken,
  messages,
  onPresignedFailure,
}: {
  artifact: ReplayArtifact;
  accessToken: string;
  messages: Messages;
  onPresignedFailure: () => void;
}) {
  const presignedSrc = artifact.access.mode === "presigned" ? artifact.access.url : null;
  const [blobSrc, setBlobSrc] = useState<string | null>(null);

  useEffect(() => {
    if (artifact.access.mode === "presigned") {
      return;
    }

    let objectUrl: string | null = null;
    const controller = new AbortController();

    void getReplayArtifactBlob({
      access: artifact.access,
      accessToken,
      kind: artifact.kind,
      signal: controller.signal,
    })
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobSrc(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setBlobSrc(null);
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [accessToken, artifact]);

  const src = presignedSrc ?? blobSrc;
  const time = formatGameTime(artifact.game_time_ms);
  const label = artifact.kind === "anchor_frame" ? messages.anchorFrame : messages.verificationFrame;
  const alt =
    artifact.kind === "anchor_frame"
      ? fill(messages.anchorFrameAlt, { time })
      : fill(messages.verificationFrameAlt, { time });

  return (
    <figure className="replay-artifact">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt}
          onError={() => {
            if (artifact.access.mode === "presigned") {
              onPresignedFailure();
            }
          }}
        />
      ) : (
        <div className="replay-artifact-placeholder" aria-hidden="true" />
      )}
      <figcaption>{label}</figcaption>
    </figure>
  );
}

export function ReplayArtifactGallery({
  artifacts,
  accessToken,
  messages,
  onRefreshManifest,
}: {
  artifacts: ReplayArtifact[];
  accessToken: string;
  messages: Messages;
  onRefreshManifest: () => void;
}) {
  const sorted = useMemo(
    () => [...artifacts].sort((a, b) => a.game_time_ms - b.game_time_ms),
    [artifacts],
  );

  return (
    <div className="replay-artifact-gallery" data-testid="replay-artifact-gallery">
      {sorted.map((artifact) => (
        <ArtifactImage
          key={artifact.artifact_id}
          artifact={artifact}
          accessToken={accessToken}
          messages={messages}
          onPresignedFailure={onRefreshManifest}
        />
      ))}
    </div>
  );
}
