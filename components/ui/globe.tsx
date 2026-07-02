"use client";

import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import createGlobe, { type COBEOptions } from "cobe";
import { useMotionValue, useSpring } from "motion/react";

const MOVEMENT_DAMPING = 1400;

export type GlobeMarker = {
  id: string;
  location: [number, number];
  size?: number;
  region: string;
  headline: string;
  prompt?: string;
  article?: unknown;
};

type ProjectedMarker = GlobeMarker & {
  x: number;
  y: number;
  visible: boolean;
  scale: number;
};

const NEWS_MARKERS: GlobeMarker[] = [
  {
    id: "new-york",
    location: [40.7128, -74.006] as [number, number],
    size: 0.024,
    region: "New York",
    headline: "Markets parse rate signal",
  },
  {
    id: "london",
    location: [51.5072, -0.1276] as [number, number],
    size: 0.022,
    region: "London",
    headline: "Parliament weighs media rules",
  },
  {
    id: "tokyo",
    location: [35.6762, 139.6503] as [number, number],
    size: 0.02,
    region: "Tokyo",
    headline: "Chip supply chain expands",
  },
  {
    id: "sao-paulo",
    location: [-23.5505, -46.6333] as [number, number],
    size: 0.024,
    region: "Sao Paulo",
    headline: "Climate desk tracks rainfall",
  },
  {
    id: "delhi",
    location: [28.6139, 77.209] as [number, number],
    size: 0.022,
    region: "Delhi",
    headline: "Air quality brief updates",
  },
  {
    id: "cairo",
    location: [30.0444, 31.2357] as [number, number],
    size: 0.02,
    region: "Cairo",
    headline: "Regional summit sources align",
  },
];

const GLOBE_CONFIG: COBEOptions = {
  width: 800,
  height: 800,
  onRender: () => {},
  devicePixelRatio: 2,
  phi: 0,
  theta: 0.3,
  dark: 0,
  diffuse: 0.4,
  mapSamples: 16000,
  mapBrightness: 1.2,
  baseColor: [1, 1, 1],
  markerColor: [251 / 255, 100 / 255, 21 / 255],
  glowColor: [1, 1, 1],
  markerElevation: 0.025,
  markers: [],
  arcs: [
    { id: "ny-london", from: [40.7128, -74.006], to: [51.5072, -0.1276] },
    { id: "london-delhi", from: [51.5072, -0.1276], to: [28.6139, 77.209] },
    { id: "tokyo-ny", from: [35.6762, 139.6503], to: [40.7128, -74.006] },
    { id: "sao-paulo-cairo", from: [-23.5505, -46.6333], to: [30.0444, 31.2357] },
  ],
  arcColor: [45 / 255, 92 / 255, 255 / 255],
  arcWidth: 0.32,
  arcHeight: 0.26,
};

export function Globe({
  className = "",
  config,
  markers = NEWS_MARKERS,
  onMarkerClick,
}: {
  className?: string;
  config?: COBEOptions;
  markers?: GlobeMarker[];
  onMarkerClick?: (marker: GlobeMarker) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phiRef = useRef(0);
  const widthRef = useRef(0);
  const [renderPhi, setRenderPhi] = useState(0);
  const pointerInteracting = useRef<number | null>(null);
  const pointerInteractionMovement = useRef(0);

  const r = useMotionValue(0);
  const rs = useSpring(r, {
    mass: 1,
    damping: 30,
    stiffness: 100,
  });

  const updatePointerInteraction = (value: number | null) => {
    pointerInteracting.current = value;
    if (canvasRef.current) {
      canvasRef.current.style.cursor = value !== null ? "grabbing" : "grab";
    }
  };

  const updateMovement = (clientX: number) => {
    if (pointerInteracting.current !== null) {
      const delta = clientX - pointerInteracting.current;
      pointerInteractionMovement.current = delta;
      r.set(r.get() + delta / MOVEMENT_DAMPING);
    }
  };

  const globeConfig = useMemo<COBEOptions>(() => ({
    ...GLOBE_CONFIG,
    ...(config || {}),
    markers: [],
    arcs: [],
  }), [config, markers]);

  const projectedMarkers = useMemo<ProjectedMarker[]>(() => {
    const theta = Number(globeConfig.theta || 0);
    return markers
      .filter((marker) => marker.region && marker.headline && Number.isFinite(marker.location?.[0]) && Number.isFinite(marker.location?.[1]))
      .slice(0, 18)
      .map((marker) => {
      const lat = marker.location[0] * Math.PI / 180;
      const lng = marker.location[1] * Math.PI / 180;
      const rotatedLng = lng - renderPhi;
      const x = Math.cos(lat) * Math.sin(rotatedLng);
      const y0 = Math.sin(lat);
      const z0 = Math.cos(lat) * Math.cos(rotatedLng);
      const y = y0 * Math.cos(theta) - z0 * Math.sin(theta);
      const z = y0 * Math.sin(theta) + z0 * Math.cos(theta);
      return {
        ...marker,
        x: 50 + x * 43,
        y: 50 - y * 43,
        visible: z > -0.03,
        scale: Math.max(0.72, Math.min(1.06, 0.82 + z * 0.22)),
      };
    });
  }, [globeConfig.theta, markers, renderPhi]);

  useEffect(() => {
    const onResize = () => {
      if (canvasRef.current) {
        widthRef.current = canvasRef.current.offsetWidth;
      }
    };

    window.addEventListener("resize", onResize);
    onResize();

    const globe = createGlobe(canvasRef.current!, {
      ...globeConfig,
      width: widthRef.current * 2,
      height: widthRef.current * 2,
    });

    const animate = () => {
      if (pointerInteracting.current === null) phiRef.current += 0.006;
      globe.update({
        phi: phiRef.current + rs.get(),
        width: widthRef.current * 2,
        height: widthRef.current * 2,
      });
      setRenderPhi(phiRef.current + rs.get());
      animationFrame = requestAnimationFrame(animate);
    };

    let animationFrame = requestAnimationFrame(animate);

    setTimeout(() => (canvasRef.current!.style.opacity = "1"), 0);

    return () => {
      cancelAnimationFrame(animationFrame);
      globe.destroy();
      window.removeEventListener("resize", onResize);
    };
  }, [rs, globeConfig]);

  return (
    <div className={`absolute inset-0 mx-auto aspect-square w-full max-w-[600px] ${className}`}>
      <canvas
        className="h-full w-full opacity-0 transition-opacity duration-500"
        ref={canvasRef}
        onPointerDown={(event) => {
          pointerInteracting.current = event.clientX;
          updatePointerInteraction(event.clientX);
        }}
        onPointerUp={() => updatePointerInteraction(null)}
        onPointerOut={() => updatePointerInteraction(null)}
        onMouseMove={(event) => updateMovement(event.clientX)}
        onTouchMove={(event) =>
          event.touches[0] && updateMovement(event.touches[0].clientX)
        }
      />
      <div className="news-marker-layer" aria-label="Clickable global trends">
        {projectedMarkers.map((marker) => (
        <button
          type="button"
          className="news-marker-label"
          key={marker.id}
          onClick={() => onMarkerClick?.(marker)}
          style={{
            "--marker-x": `${marker.x}%`,
            "--marker-y": `${marker.y}%`,
            "--marker-opacity": marker.visible ? 1 : 0,
            "--marker-scale": marker.scale,
          } as CSSProperties}
          aria-hidden={!marker.visible}
          tabIndex={marker.visible ? 0 : -1}
        >
          <span>{marker.region}</span>
          <strong>{marker.headline}</strong>
        </button>
        ))}
      </div>
    </div>
  );
}
