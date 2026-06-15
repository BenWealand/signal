"use client";

import { type CSSProperties, useEffect, useMemo, useRef } from "react";
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
  markers: NEWS_MARKERS.map(({ id, location, size = 0.022 }) => ({ id, location, size })),
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
    markers: markers.map(({ id, location, size = 0.022 }) => ({ id, location, size })),
    arcs: [],
  }), [config, markers]);

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
        {markers.slice(0, 8).map((marker, index) => (
        <button
          type="button"
          className={`news-marker-label marker-pos-${index % 8}`}
          key={marker.id}
          onClick={() => onMarkerClick?.(marker)}
          style={{ "--marker-delay": `${index * -0.42}s` } as CSSProperties}
        >
          <span>{marker.region}</span>
          <strong>{marker.headline}</strong>
        </button>
        ))}
      </div>
    </div>
  );
}
