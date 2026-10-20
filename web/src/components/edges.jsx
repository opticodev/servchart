import { BaseEdge, getBezierPath, getSmoothStepPath } from "@xyflow/react";
import { roundedPath } from "../routing.js";

// Lines that run side by side would share the same vertical segment and become one thick bus.
// Each edge gets a "lane" (from its id) that shifts its vertical segment a few pixels.
function lane(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return (Math.abs(h) % 7) - 3; // -3 .. 3
}

export function LaneEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, markerStart, style, label, labelStyle, labelShowBg, labelBgStyle, labelBgPadding, labelBgBorderRadius, interactionWidth }) {
  let path;
  let labelX;
  let labelY;
  const route = data?.route;
  if (route && route.length >= 2) {
    // routed through the gaps between cards (routing.js); pin both ends to the handles React Flow measured
    const pts = route.map((p) => ({ ...p }));
    const dy0 = sourceY - pts[0].y;
    const dy1 = targetY - pts[pts.length - 1].y;
    pts[0] = { x: sourceX, y: sourceY };
    pts[pts.length - 1] = { x: targetX, y: targetY };
    if (pts.length > 2) {
      pts[1].y += dy0; // keep the first and last runs horizontal
      pts[pts.length - 2].y += dy1;
    }
    // curved style: the same route (around cards, bundled between servers) with wide, smooth turns
    [path, labelX, labelY] = roundedPath(pts, data?.curved ? 26 : 10);
  } else if (data?.curved) {
    [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  } else {
    const spread = lane(id) * 7;
    [path, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
      borderRadius: 10,
      offset: 18 + Math.abs(spread),
      centerX: (sourceX + targetX) / 2 + spread,
    });
  }
  return (
    <BaseEdge
      id={id}
      path={path}
      labelX={labelX}
      labelY={labelY}
      label={label}
      labelStyle={labelStyle}
      labelShowBg={labelShowBg}
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      labelBgBorderRadius={labelBgBorderRadius}
      markerEnd={markerEnd}
      markerStart={markerStart}
      style={style}
      interactionWidth={interactionWidth ?? 14}
    />
  );
}

export const edgeTypes = { lane: LaneEdge };
