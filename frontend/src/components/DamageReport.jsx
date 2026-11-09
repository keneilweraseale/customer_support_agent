import { useEffect, useRef, useState } from "react";

import { submitDamageReport } from "../api.js";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

function createIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("The captured photo could not be prepared."));
    };
    reader.onerror = () => reject(new Error("The captured photo could not be prepared."));
    reader.readAsDataURL(blob);
  });
}

function cameraErrorMessage(error) {
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
    return "Camera access was denied. Allow camera access in your browser settings, then try again.";
  }
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") {
    return "No camera was found. Use a supported device with a camera to submit a report.";
  }
  if (error?.name === "NotReadableError" || error?.name === "TrackStartError") {
    return "The camera is unavailable or being used by another app. Close other camera apps and try again.";
  }
  return "The camera could not be started. Check your camera connection and browser permissions.";
}

export default function DamageReport({ authorizationToken, onBack }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const disposedRef = useRef(false);
  const submissionKeyRef = useRef(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraBusy, setCameraBusy] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [photoConfirmed, setPhotoConfirmed] = useState(false);
  const [orderId, setOrderId] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [report, setReport] = useState(null);
  const [photoUrl, setPhotoUrl] = useState("");

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOpen(false);
  }

  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!cameraOpen || !streamRef.current || !videoRef.current) return;
    const video = videoRef.current;
    video.srcObject = streamRef.current;
    video.play().catch((playError) => {
      stopCamera();
      setError(cameraErrorMessage(playError));
    });
  }, [cameraOpen]);

  useEffect(() => {
    if (!photo) {
      setPhotoUrl("");
      return undefined;
    }
    const objectUrl = URL.createObjectURL(photo);
    setPhotoUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [photo]);

  async function openCamera() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser does not support camera access. Use a supported device with a camera.");
      return;
    }

    setCameraBusy(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      if (disposedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      setCameraOpen(true);
    } catch (cameraError) {
      stopCamera();
      setError(cameraErrorMessage(cameraError));
    } finally {
      if (!disposedRef.current) setCameraBusy(false);
    }
  }

  function capturePhoto() {
    const video = videoRef.current;
    if (!video?.videoWidth || !video.videoHeight || capturing) {
      setError("The camera is not ready yet. Wait for the preview, then try again.");
      return;
    }
    setError("");
    setCapturing(true);
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      setCapturing(false);
      setError("The photo could not be captured. Please try again.");
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        setCapturing(false);
        if (!blob) {
          setError("The photo could not be captured. Please try again.");
          return;
        }
        if (blob.size > MAX_IMAGE_BYTES) {
          setError("This photo is larger than 5 MB. Try again with a lower-resolution camera.");
          return;
        }
        setPhoto(blob);
        setPhotoConfirmed(false);
        stopCamera();
      },
      "image/jpeg",
      0.88,
    );
  }

  async function submitReport(event) {
    event.preventDefault();
    if (!photo || !photoConfirmed || !orderId.trim() || submitting) return;
    setError("");
    setSubmitting(true);
    try {
      const imageData = await blobToDataUrl(photo);
      submissionKeyRef.current ??= createIdempotencyKey();
      const result = await submitDamageReport({
        authorizationToken,
        orderId: orderId.trim(),
        imageData,
        description: description.trim(),
        idempotencyKey: submissionKeyRef.current,
      });
      setReport(result);
      setPhoto(null);
      submissionKeyRef.current = null;
    } catch (submitError) {
      if (submitError.status === 401) {
        setError("Your session has expired. Sign in again before submitting your report.");
      } else {
        setError(submitError.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  function retakePhoto() {
    setPhoto(null);
    setPhotoConfirmed(false);
    submissionKeyRef.current = null;
    setError("");
    void openCamera();
  }

  return (
    <section aria-labelledby="damage-report-title" style={styles.page}>
      <div style={styles.header}>
        <div>
          <p style={styles.eyebrow}>CUSTOMER SUPPORT</p>
          <h2 id="damage-report-title" style={styles.title}>Live Picture</h2>
          <p style={styles.subtitle}>Show us the damage so our team can review your report.</p>
        </div>
        <button onClick={onBack} style={styles.backButton} type="button">
          Back to chat
        </button>
      </div>

      {report ? (
        <div aria-live="polite" role="status" style={styles.success}>
          <div aria-hidden="true" style={styles.successIcon}>✓</div>
          <h3 style={styles.successTitle}>Report received</h3>
          <p style={styles.body}>
            {report.message} The support team can review your attached photo and message.
            Your report reference is <strong>{report.report_id}</strong>.
            Submitting a report does not mean a refund or replacement has been approved.
          </p>
          <button onClick={onBack} style={styles.primaryButton} type="button">Back to chat</button>
        </div>
      ) : (
        <form onSubmit={submitReport} style={styles.form}>
          <div style={styles.instructions}>
            <span aria-hidden="true" style={styles.step}>1</span>
            <p style={styles.body}>
              Use your camera to take a new, clear photo of the damaged item. Include the
              damaged area and as much of the item as possible.
            </p>
          </div>

          <div style={styles.cameraFrame}>
            {photo ? (
              <img alt="Preview of the newly captured product photo" src={photoUrl} style={styles.preview} />
            ) : cameraOpen ? (
              <video aria-label="Live camera preview" autoPlay playsInline ref={videoRef} style={styles.preview} />
            ) : (
              <div style={styles.cameraPlaceholder}>
                <span aria-hidden="true" style={styles.cameraIcon}>◎</span>
                <strong>Your camera preview will appear here</strong>
                <span>Camera access is used only when you choose Open Camera.</span>
              </div>
            )}
          </div>

          <div style={styles.actions}>
            {!photo && !cameraOpen && (
              <button disabled={cameraBusy} onClick={openCamera} style={styles.primaryButton} type="button">
                {cameraBusy ? "Opening camera…" : "Open Camera"}
              </button>
            )}
            {cameraOpen && (
              <>
                <button disabled={capturing} onClick={capturePhoto} style={styles.primaryButton} type="button">
                  {capturing ? "Taking picture…" : "Take Picture"}
                </button>
                <button onClick={stopCamera} style={styles.secondaryButton} type="button">Close Camera</button>
              </>
            )}
            {photo && (
              <>
                <button onClick={retakePhoto} style={styles.secondaryButton} type="button">Retake</button>
                <button
                  onClick={() => setPhotoConfirmed(true)}
                  style={photoConfirmed ? styles.confirmedButton : styles.primaryButton}
                  type="button"
                >
                  {photoConfirmed ? "Photo confirmed" : "Use Photo"}
                </button>
              </>
            )}
          </div>

          <div style={styles.details}>
            <label htmlFor="damage-order" style={styles.label}>Order reference</label>
            <input
              autoComplete="off"
              id="damage-order"
              maxLength={64}
              onChange={(event) => {
                submissionKeyRef.current = null;
                setOrderId(event.target.value.toUpperCase());
              }}
              placeholder="For example, ORD-1001"
              required
              style={styles.input}
              value={orderId}
            />
            <label htmlFor="damage-description" style={styles.label}>
              Message for support (required)
            </label>
            <textarea
              id="damage-description"
              maxLength={1000}
              onChange={(event) => {
                submissionKeyRef.current = null;
                setDescription(event.target.value);
              }}
              placeholder="Tell us what happened or where the item is damaged."
              required
              rows={3}
              style={styles.input}
              value={description}
            />
          </div>

          {error && <p aria-live="polite" role="alert" style={styles.error}>{error}</p>}

          <div style={styles.submitRow}>
            <p style={styles.privacy}>
              Your photo and details are securely sent to support for review.
            </p>
            <button
              disabled={
                !photoConfirmed || !orderId.trim() || !description.trim() || submitting
              }
              style={styles.primaryButton}
              type="submit"
            >
              {submitting ? "Submitting report…" : "Submit Report"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

const styles = {
  page: {
    background: "#FFFFFF",
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: "28px clamp(18px, 5vw, 56px)",
  },
  header: {
    alignItems: "flex-start",
    borderBottom: "1px solid #E2E8F0",
    display: "flex",
    gap: 20,
    justifyContent: "space-between",
    margin: "0 auto 22px",
    maxWidth: 720,
    paddingBottom: 18,
  },
  eyebrow: { color: "#1D4ED8", fontSize: 11, fontWeight: 700, letterSpacing: 1.2, margin: "0 0 6px" },
  title: { color: "#1F2937", fontSize: 25, margin: 0 },
  subtitle: { color: "#64748B", fontSize: 14, lineHeight: 1.5, margin: "7px 0 0" },
  backButton: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 9,
    color: "#334155",
    cursor: "pointer",
    flexShrink: 0,
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    padding: "9px 12px",
  },
  form: { margin: "0 auto", maxWidth: 720 },
  instructions: { alignItems: "flex-start", display: "flex", gap: 12, marginBottom: 16 },
  step: {
    alignItems: "center",
    background: "#EFF6FF",
    borderRadius: "50%",
    color: "#1D4ED8",
    display: "flex",
    flex: "0 0 28px",
    fontSize: 13,
    fontWeight: 700,
    height: 28,
    justifyContent: "center",
  },
  body: { color: "#475569", fontSize: 14, lineHeight: 1.55, margin: 0 },
  cameraFrame: {
    alignItems: "center",
    background: "#0F172A",
    border: "1px solid #CBD5E1",
    borderRadius: 16,
    display: "flex",
    justifyContent: "center",
    minHeight: 230,
    overflow: "hidden",
    position: "relative",
  },
  preview: { display: "block", maxHeight: 440, objectFit: "contain", width: "100%" },
  cameraPlaceholder: {
    alignItems: "center",
    color: "#CBD5E1",
    display: "flex",
    flexDirection: "column",
    fontSize: 13,
    gap: 8,
    padding: 28,
    textAlign: "center",
  },
  cameraIcon: { color: "#93C5FD", fontSize: 38, lineHeight: 1 },
  actions: { display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "center", margin: "14px 0 20px" },
  primaryButton: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 9,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 600,
    padding: "11px 16px",
  },
  secondaryButton: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 9,
    color: "#334155",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 600,
    padding: "10px 15px",
  },
  confirmedButton: {
    background: "#0F766E",
    border: 0,
    borderRadius: 9,
    color: "#FFFFFF",
    cursor: "default",
    font: "inherit",
    fontSize: 14,
    fontWeight: 600,
    padding: "11px 16px",
  },
  details: { display: "grid", gap: 8 },
  label: { color: "#334155", fontSize: 13, fontWeight: 600, marginTop: 4 },
  optional: { color: "#64748B", fontWeight: 400 },
  input: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 8,
    color: "#1F2937",
    font: "inherit",
    fontSize: 14,
    outlineColor: "#1D4ED8",
    padding: "10px 12px",
    resize: "vertical",
    width: "100%",
  },
  error: {
    background: "#FEF2F2",
    border: "1px solid #FECACA",
    borderRadius: 8,
    color: "#991B1B",
    fontSize: 13,
    lineHeight: 1.5,
    margin: "14px 0",
    padding: 11,
  },
  submitRow: {
    alignItems: "center",
    borderTop: "1px solid #E2E8F0",
    display: "flex",
    flexWrap: "wrap",
    gap: 14,
    justifyContent: "space-between",
    marginTop: 18,
    paddingTop: 16,
  },
  privacy: { color: "#64748B", flex: "1 1 260px", fontSize: 12, lineHeight: 1.5, margin: 0 },
  success: {
    background: "#F0FDFA",
    border: "1px solid #99F6E4",
    borderRadius: 16,
    margin: "48px auto",
    maxWidth: 520,
    padding: 28,
    textAlign: "center",
  },
  successIcon: {
    alignItems: "center",
    background: "#CCFBF1",
    borderRadius: "50%",
    color: "#0F766E",
    display: "flex",
    fontSize: 24,
    fontWeight: 700,
    height: 48,
    justifyContent: "center",
    margin: "0 auto",
    width: 48,
  },
  successTitle: { color: "#134E4A", fontSize: 20, margin: "14px 0 8px" },
};
