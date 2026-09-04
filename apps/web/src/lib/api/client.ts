/**
 * Typed HTTP client for the NaviSight API.
 *
 * Every response is parsed through its Zod schema, so a contract change fails
 * loudly at the boundary with the offending field named.
 *
 * Failures are modelled as a single `ApiClientError` carrying the server's
 * stable error code, so the UI can distinguish "database is down" from "vessel
 * not found" from "the network dropped" and render the right state, rather
 * than showing one generic message for everything (SOUL.md §11).
 */

import type { z } from "zod";

import {
  apiErrorSchema,
  activeVesselSchema,
  dataQualitySchema,
  datasetStatusSchema,
  distributionResponseSchema,
  latestObservationSchema,
  mapResponseSchema,
  nearbyVesselSchema,
  portActivitySchema,
  portSchema,
  paginatedObservationsSchema,
  readySchema,
  speedDistributionSchema,
  trafficResponseSchema,
  vesselDetailSchema,
  vesselSummarySchema,
  vesselTrackSchema,
} from "./types";
import { z as zod } from "zod";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** How a request failed, in terms the UI can branch on. */
export type ApiFailureKind =
  | "network"
  | "not_found"
  | "validation"
  | "unavailable"
  | "not_configured"
  | "contract"
  | "server";

export class ApiClientError extends Error {
  readonly kind: ApiFailureKind;
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: Record<string, unknown> | null;

  constructor(init: {
    kind: ApiFailureKind;
    code: string;
    message: string;
    status: number;
    requestId?: string | null;
    details?: Record<string, unknown> | null;
  }) {
    super(init.message);
    this.name = "ApiClientError";
    this.kind = init.kind;
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? null;
  }

  /** Whether retrying could plausibly succeed. Drives TanStack Query retries. */
  get isRetryable(): boolean {
    return this.kind === "network" || this.kind === "unavailable";
  }
}

function classify(status: number, code: string): ApiFailureKind {
  if (code === "AI_NOT_CONFIGURED" || code === "PORT_DATA_NOT_CONFIGURED") {
    return "not_configured";
  }
  if (code === "DATABASE_UNAVAILABLE" || status === 503) return "unavailable";
  if (status === 404) return "not_found";
  if (status === 400 || status === 422) return "validation";
  return "server";
}

type QueryValue = string | number | boolean | null | undefined;

function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = new URL(path.replace(/^\//, ""), `${API_BASE_URL.replace(/\/$/, "")}/`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(
  schema: z.ZodType<T>,
  path: string,
  params?: Record<string, QueryValue>,
  init?: RequestInit,
): Promise<T> {
  const url = buildUrl(path, params);

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    // A thrown fetch means the API was unreachable, which is a different
    // problem from an API that answered with an error.
    throw new ApiClientError({
      kind: "network",
      code: "NETWORK_ERROR",
      message:
        "Could not reach the NaviSight API. Check that it is running and that " +
        "NEXT_PUBLIC_API_BASE_URL points at it.",
      status: 0,
      details: { url, cause: String(cause) },
    });
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const parsed = apiErrorSchema.safeParse(body);
    if (parsed.success) {
      const { code, message, requestId, details } = parsed.data.error;
      throw new ApiClientError({
        kind: classify(response.status, code),
        code,
        message,
        status: response.status,
        requestId,
        details: details ?? null,
      });
    }
    throw new ApiClientError({
      kind: classify(response.status, "UNKNOWN"),
      code: "UNKNOWN",
      message: `The API returned ${response.status} ${response.statusText}.`,
      status: response.status,
    });
  }

  const payload = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    throw new ApiClientError({
      kind: "contract",
      code: "RESPONSE_CONTRACT_MISMATCH",
      message:
        `The API response did not match the expected shape at ` +
        `"${issue?.path.join(".") || "(root)"}": ${issue?.message}. ` +
        `The API and web app versions may be out of step.`,
      status: response.status,
      details: { path, issues: parsed.error.issues.slice(0, 5) },
    });
  }
  return parsed.data;
}

/* ------------------------------------------------------------------------ */
/* Endpoints                                                                 */
/* ------------------------------------------------------------------------ */

export const api = {
  ready: () => request(readySchema, "/api/v1/ready"),

  datasetStatus: () => request(datasetStatusSchema, "/api/v1/dataset/status"),

  dataQuality: () => request(dataQualitySchema, "/api/v1/dataset/quality"),

  searchVessels: (params: {
    q?: string;
    vesselType?: number;
    family?: string;
    hasImo?: boolean;
    limit?: number;
    skip?: number;
  }) => request(zod.array(vesselSummarySchema), "/api/v1/vessels", params),

  vessel: (mmsi: string) => request(vesselDetailSchema, `/api/v1/vessels/${mmsi}`),

  latestObservation: (mmsi: string) =>
    request(latestObservationSchema, `/api/v1/vessels/${mmsi}/latest`),

  positions: (mmsi: string, params: { limit?: number; cursor?: string } = {}) =>
    request(paginatedObservationsSchema, `/api/v1/vessels/${mmsi}/positions`, params),

  track: (mmsi: string, params: { start?: string; end?: string; max_points?: number } = {}) =>
    request(vesselTrackSchema, `/api/v1/vessels/${mmsi}/track`, params),

  mapVessels: (params: {
    west: number;
    south: number;
    east: number;
    north: number;
    limit?: number;
    vesselType?: number;
    family?: string;
    transceiver?: "A" | "B";
    minSpeed?: number;
    maxSpeed?: number;
    at?: string;
  }) => request(mapResponseSchema, "/api/v1/map/vessels", params),

  nearby: (params: {
    longitude: number;
    latitude: number;
    radiusKm?: number;
    limit?: number;
    vesselType?: number;
  }) => request(zod.array(nearbyVesselSchema), "/api/v1/geo/nearby", params),

  ports: (params: { q?: string; limit?: number; skip?: number } = {}) =>
    request(zod.array(portSchema), "/api/v1/ports", params),

  port: (portId: string) => request(portSchema, `/api/v1/ports/${portId}`),

  portActivity: (portId: string, params: { radiusKm?: number; limit?: number } = {}) =>
    request(portActivitySchema, `/api/v1/ports/${portId}/activity`, params),

  traffic: (params: { start?: string; end?: string; interval?: "hour" | "15min" } = {}) =>
    request(trafficResponseSchema, "/api/v1/analytics/traffic", params),

  vesselTypes: () => request(distributionResponseSchema, "/api/v1/analytics/vessel-types"),

  transceivers: () => request(distributionResponseSchema, "/api/v1/analytics/transceivers"),

  navStatus: () => request(distributionResponseSchema, "/api/v1/analytics/nav-status"),

  speedDistribution: (params: { start?: string; end?: string } = {}) =>
    request(speedDistributionSchema, "/api/v1/analytics/speed", params),

  activeVessels: (params: { start?: string; end?: string; limit?: number } = {}) =>
    request(zod.array(activeVesselSchema), "/api/v1/analytics/active-vessels", params),
};
