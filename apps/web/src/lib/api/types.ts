/**
 * API contract, expressed as Zod schemas.
 *
 * The API is a separate service that can be deployed independently, so its
 * responses are *untrusted input* to this app in the same way any network
 * payload is. Validating at the boundary means a contract change surfaces as a
 * clear parse error naming the field, rather than as `undefined` propagating
 * into a chart three components deep.
 *
 * Types are inferred from the schemas so there is exactly one definition.
 */

import { z } from "zod";

export const coordinatesSchema = z.object({
  longitude: z.number(),
  latitude: z.number(),
});

export const vesselTypeInfoSchema = z.object({
  code: z.number().nullable().default(null),
  label: z.string(),
  family: z.string(),
});

export const vesselSummarySchema = z.object({
  mmsi: z.string(),
  name: z.string().nullable().default(null),
  imo: z.string().nullable().default(null),
  callSign: z.string().nullable().default(null),
  vesselType: vesselTypeInfoSchema,
});

export const vesselDimensionsSchema = z.object({
  lengthMeters: z.number().nullable().default(null),
  widthMeters: z.number().nullable().default(null),
  draftMeters: z.number().nullable().default(null),
});

export const vesselDetailSchema = vesselSummarySchema.extend({
  dimensions: vesselDimensionsSchema.nullable().default(null),
  cargo: z.number().nullable().default(null),
  firstSeenAt: z.string().nullable().default(null),
  lastSeenAt: z.string().nullable().default(null),
  metadataUpdatedAt: z.string().nullable().default(null),
  observationCount: z.number().nullable().default(null),
});

export const navigationStateSchema = z.object({
  speedOverGroundKnots: z.number().nullable().default(null),
  courseOverGroundDegrees: z.number().nullable().default(null),
  headingDegrees: z.number().nullable().default(null),
  status: z.number().nullable().default(null),
  statusLabel: z.string(),
});

export const observationSchema = z.object({
  mmsi: z.string(),
  timestamp: z.string(),
  coordinates: coordinatesSchema,
  navigation: navigationStateSchema,
  transceiverClass: z.string().nullable().default(null),
});

export const latestObservationSchema = observationSchema.extend({
  name: z.string().nullable().default(null),
  vesselType: vesselTypeInfoSchema,
});

export const pageSchema = z.object({
  nextCursor: z.string().nullable().default(null),
  hasMore: z.boolean(),
  returned: z.number(),
});

export const paginatedObservationsSchema = z.object({
  items: z.array(observationSchema),
  page: pageSchema,
});

/**
 * Track metadata.
 *
 * `simplified`, `rawPointCount`, and `method` are required, not optional: the
 * UI is obliged to tell the user when a path has been reduced, so the shape
 * makes it impossible to render a track without knowing (SOUL.md §4).
 */
export const trackMetaSchema = z.object({
  rawPointCount: z.number(),
  returnedPointCount: z.number(),
  simplified: z.boolean(),
  method: z.enum(["none", "douglas_peucker", "uniform_sample"]),
  interpolated: z.boolean(),
  start: z.string().nullable().default(null),
  end: z.string().nullable().default(null),
});

export const trackPointSchema = z.object({
  timestamp: z.string(),
  coordinates: coordinatesSchema,
  speedOverGroundKnots: z.number().nullable().default(null),
  courseOverGroundDegrees: z.number().nullable().default(null),
});

export const vesselTrackSchema = z.object({
  mmsi: z.string(),
  points: z.array(trackPointSchema),
  meta: trackMetaSchema,
});

export const mapVesselSchema = z.object({
  mmsi: z.string(),
  name: z.string().nullable().default(null),
  coordinates: coordinatesSchema,
  timestamp: z.string(),
  headingDegrees: z.number().nullable().default(null),
  courseOverGroundDegrees: z.number().nullable().default(null),
  speedOverGroundKnots: z.number().nullable().default(null),
  vesselType: z.number().nullable().default(null),
  family: z.string(),
});

export const mapClusterSchema = z.object({
  coordinates: coordinatesSchema,
  count: z.number(),
});

export const mapResponseSchema = z.object({
  mode: z.enum(["vessels", "clusters"]),
  vessels: z.array(mapVesselSchema).default([]),
  clusters: z.array(mapClusterSchema).default([]),
  totalInViewport: z.number(),
  truncated: z.boolean(),
});

export const nearbyVesselSchema = z.object({
  vessel: vesselSummarySchema,
  coordinates: coordinatesSchema,
  timestamp: z.string(),
  distanceKm: z.number(),
  distanceNauticalMiles: z.number(),
  speedOverGroundKnots: z.number().nullable().default(null),
});

export const timeBucketSchema = z.object({
  bucket: z.string(),
  observations: z.number(),
  distinctVessels: z.number().nullable().default(null),
});

export const trafficResponseSchema = z.object({
  buckets: z.array(timeBucketSchema),
  interval: z.enum(["hour", "15min"]),
  start: z.string(),
  end: z.string(),
  totalObservations: z.number(),
});

export const categoryCountSchema = z.object({
  key: z.string(),
  label: z.string(),
  count: z.number(),
});

export const distributionResponseSchema = z.object({
  categories: z.array(categoryCountSchema),
  total: z.number(),
  /** Which collection produced this — vessels or observations. Always shown. */
  basis: z.string(),
});

export const speedBucketSchema = z.object({
  label: z.string(),
  lowerKnots: z.number(),
  upperKnots: z.number().nullable().default(null),
  count: z.number(),
});

export const speedDistributionSchema = z.object({
  buckets: z.array(speedBucketSchema),
  total: z.number(),
  note: z.string(),
});

export const activeVesselSchema = z.object({
  vessel: vesselSummarySchema,
  observations: z.number(),
});

export const datasetStatusSchema = z.object({
  configured: z.boolean(),
  hasData: z.boolean(),
  dataset: z.string(),
  isHistorical: z.literal(true),
  counts: z.object({
    positions: z.number(),
    vessels: z.number(),
    latestStates: z.number(),
  }),
  coverage: z.object({
    start: z.string().nullable().default(null),
    end: z.string().nullable().default(null),
  }),
  lastIngestion: z
    .object({
      status: z.string().nullable().default(null),
      sourceFile: z.string().nullable().default(null),
      startedAt: z.string().nullable().default(null),
      completedAt: z.string().nullable().default(null),
      rowsRead: z.number().nullable().default(null),
      positionsInserted: z.number().nullable().default(null),
      positionsDuplicate: z.number().nullable().default(null),
      rowsRejected: z.number().nullable().default(null),
    })
    .nullable()
    .default(null),
  portsConfigured: z.boolean(),
  aiConfigured: z.boolean(),
});

export const dataQualitySchema = z.object({
  source: z.string(),
  rowsRead: z.number(),
  rowsRejected: z.number(),
  exactDuplicates: z.number(),
  fields: z.array(
    z.object({
      field: z.string(),
      present: z.number(),
      missing: z.number(),
      missingPercent: z.number(),
    }),
  ),
  generatedAt: z.string().nullable().default(null),
});

export const readySchema = z.object({
  status: z.enum(["ready", "degraded"]),
  database: z.boolean(),
  hasData: z.boolean(),
  aiConfigured: z.boolean(),
});

/** The API's error envelope. Shared by every failing response. */
export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    requestId: z.string(),
    details: z.record(z.string(), z.unknown()).optional(),
  }),
});

export type Coordinates = z.infer<typeof coordinatesSchema>;
export type VesselTypeInfo = z.infer<typeof vesselTypeInfoSchema>;
export type VesselSummary = z.infer<typeof vesselSummarySchema>;
export type VesselDetail = z.infer<typeof vesselDetailSchema>;
export type Observation = z.infer<typeof observationSchema>;
export type LatestObservation = z.infer<typeof latestObservationSchema>;
export type PaginatedObservations = z.infer<typeof paginatedObservationsSchema>;
export type TrackMeta = z.infer<typeof trackMetaSchema>;
export type TrackPoint = z.infer<typeof trackPointSchema>;
export type VesselTrack = z.infer<typeof vesselTrackSchema>;
export type MapVessel = z.infer<typeof mapVesselSchema>;
export type MapCluster = z.infer<typeof mapClusterSchema>;
export type MapResponse = z.infer<typeof mapResponseSchema>;
export type NearbyVessel = z.infer<typeof nearbyVesselSchema>;
export type TrafficResponse = z.infer<typeof trafficResponseSchema>;
export type DistributionResponse = z.infer<typeof distributionResponseSchema>;
export type SpeedDistribution = z.infer<typeof speedDistributionSchema>;
export type ActiveVessel = z.infer<typeof activeVesselSchema>;
export type DatasetStatus = z.infer<typeof datasetStatusSchema>;
export type DataQuality = z.infer<typeof dataQualitySchema>;
export type Ready = z.infer<typeof readySchema>;
