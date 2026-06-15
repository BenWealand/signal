Globe:

---
title: Globe
date: 2023-08-02
description: An autorotating, interactive, and highly performant globe made using WebGL.
author: dillionverma
published: true
video: https://cdn.magicui.design/globe.mp4
---

<ComponentPreview name="globe-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/globe
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Install the following dependencies:</Step>

```bash
npm install cobe motion
```

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import { useEffect, useRef } from "react"
import createGlobe, { type COBEOptions } from "cobe"
import { useMotionValue, useSpring } from "motion/react"

import { cn } from "@/lib/utils"

const MOVEMENT_DAMPING = 1400

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
  markers: [
    { location: [14.5995, 120.9842], size: 0.03 },
    { location: [19.076, 72.8777], size: 0.1 },
    { location: [23.8103, 90.4125], size: 0.05 },
    { location: [30.0444, 31.2357], size: 0.07 },
    { location: [39.9042, 116.4074], size: 0.08 },
    { location: [-23.5505, -46.6333], size: 0.1 },
    { location: [19.4326, -99.1332], size: 0.1 },
    { location: [40.7128, -74.006], size: 0.1 },
    { location: [34.6937, 135.5022], size: 0.05 },
    { location: [41.0082, 28.9784], size: 0.06 },
  ],
}

export function Globe({
  className,
  config = GLOBE_CONFIG,
}: {
  className?: string
  config?: COBEOptions
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const phiRef = useRef(0)
  const widthRef = useRef(0)
  const pointerInteracting = useRef<number | null>(null)
  const pointerInteractionMovement = useRef(0)

  const r = useMotionValue(0)
  const rs = useSpring(r, {
    mass: 1,
    damping: 30,
    stiffness: 100,
  })

  const updatePointerInteraction = (value: number | null) => {
    pointerInteracting.current = value
    if (canvasRef.current) {
      canvasRef.current.style.cursor = value !== null ? "grabbing" : "grab"
    }
  }

  const updateMovement = (clientX: number) => {
    if (pointerInteracting.current !== null) {
      const delta = clientX - pointerInteracting.current
      pointerInteractionMovement.current = delta
      r.set(r.get() + delta / MOVEMENT_DAMPING)
    }
  }

  useEffect(() => {
    const onResize = () => {
      if (canvasRef.current) {
        widthRef.current = canvasRef.current.offsetWidth
      }
    }

    window.addEventListener("resize", onResize)
    onResize()

    const globe = createGlobe(canvasRef.current!, {
      ...config,
      width: widthRef.current * 2,
      height: widthRef.current * 2,
      onRender: (state) => {
        if (!pointerInteracting.current) phiRef.current += 0.005
        state.phi = phiRef.current + rs.get()
        state.width = widthRef.current * 2
        state.height = widthRef.current * 2
      },
    })

    setTimeout(() => (canvasRef.current!.style.opacity = "1"), 0)
    return () => {
      globe.destroy()
      window.removeEventListener("resize", onResize)
    }
  }, [rs, config])

  return (
    <div
      className={cn(
        "absolute inset-0 mx-auto aspect-square w-full max-w-150",
        className
      )}
    >
      <canvas
        className={cn(
          "size-full opacity-0 transition-opacity duration-500 contain-[layout_paint_size]"
        )}
        ref={canvasRef}
        onPointerDown={(e) => {
          pointerInteracting.current = e.clientX
          updatePointerInteraction(e.clientX)
        }}
        onPointerUp={() => updatePointerInteraction(null)}
        onPointerOut={() => updatePointerInteraction(null)}
        onMouseMove={(e) => updateMovement(e.clientX)}
        onTouchMove={(e) =>
          e.touches[0] && updateMovement(e.touches[0].clientX)
        }
      />
    </div>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import { Globe } from "@/components/ui/globe"
```

```tsx showLineNumbers
<Globe />
```

## Props

| Prop        | Type          | Default | Description                                                                           |
| ----------- | ------------- | ------- | ------------------------------------------------------------------------------------- |
| `className` | `string`      | `-`     | The css classes for the component                                                     |
| `config`    | `COBEOptions` | `{}`    | The configuration options for the globe. More details [here](https://cobe.vercel.app) |

## Credits

This component is built on top of [Cobe](https://cobe.vercel.app).


Terminal:

---
title: Terminal
date: 2025-01-16
description: An implementation of the MacOS terminal. Useful for showcasing a command line interface.
author: dillionverma
published: true
---

<ComponentPreview name="terminal-demo" />

## Examples

### Custom Delays

<ComponentPreview name="terminal-demo-2" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/terminal
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import {
  Children,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type RefAttributes,
} from "react"
import {
  motion,
  useInView,
  type DOMMotionComponents,
  type HTMLMotionProps,
  type MotionProps,
} from "motion/react"

import { cn } from "@/lib/utils"

interface SequenceContextValue {
  completeItem: (index: number) => void
  activeIndex: number
  sequenceStarted: boolean
}

const SequenceContext = createContext<SequenceContextValue | null>(null)

const useSequence = () => useContext(SequenceContext)

const ItemIndexContext = createContext<number | null>(null)
const useItemIndex = () => useContext(ItemIndexContext)

const motionElements = {
  article: motion.article,
  div: motion.div,
  h1: motion.h1,
  h2: motion.h2,
  h3: motion.h3,
  h4: motion.h4,
  h5: motion.h5,
  h6: motion.h6,
  li: motion.li,
  p: motion.p,
  section: motion.section,
  span: motion.span,
} as const

type MotionElementType = Extract<
  keyof DOMMotionComponents,
  keyof typeof motionElements
>
type TerminalTypingMotionComponent = ComponentType<
  Omit<HTMLMotionProps<"span">, "ref"> & RefAttributes<HTMLElement>
>

interface AnimatedSpanProps extends MotionProps {
  children: React.ReactNode
  delay?: number
  className?: string
  startOnView?: boolean
}

export const AnimatedSpan = ({
  children,
  delay = 0,
  className,
  startOnView = false,
  ...props
}: AnimatedSpanProps) => {
  const elementRef = useRef<HTMLDivElement | null>(null)
  const isInView = useInView(elementRef as React.RefObject<Element>, {
    amount: 0.3,
    once: true,
  })

  const sequence = useSequence()
  const itemIndex = useItemIndex()
  const [hasStarted, setHasStarted] = useState(false)
  useEffect(() => {
    if (!sequence || itemIndex === null) return
    if (!sequence.sequenceStarted) return
    if (hasStarted) return
    if (sequence.activeIndex === itemIndex) {
      setHasStarted(true)
    }
  }, [sequence, hasStarted, itemIndex])

  const shouldAnimate = sequence ? hasStarted : startOnView ? isInView : true

  return (
    <motion.div
      ref={elementRef}
      initial={{ opacity: 0, y: -5 }}
      animate={shouldAnimate ? { opacity: 1, y: 0 } : { opacity: 0, y: -5 }}
      transition={{ duration: 0.3, delay: sequence ? 0 : delay / 1000 }}
      className={cn("grid text-sm font-normal tracking-tight", className)}
      onAnimationComplete={() => {
        if (!sequence) return
        if (itemIndex === null) return
        sequence.completeItem(itemIndex)
      }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

interface TypingAnimationProps extends Omit<MotionProps, "children"> {
  children: string
  className?: string
  duration?: number
  delay?: number
  as?: MotionElementType
  startOnView?: boolean
}

export const TypingAnimation = ({
  children,
  className,
  duration = 60,
  delay = 0,
  as: Component = "span",
  startOnView = true,
  ...props
}: TypingAnimationProps) => {
  if (typeof children !== "string") {
    throw new Error("TypingAnimation: children must be a string. Received:")
  }

  const MotionComponent = motionElements[
    Component
  ] as TerminalTypingMotionComponent

  const [displayedText, setDisplayedText] = useState<string>("")
  const [started, setStarted] = useState(false)
  const elementRef = useRef<HTMLElement | null>(null)
  const isInView = useInView(elementRef as React.RefObject<Element>, {
    amount: 0.3,
    once: true,
  })

  const sequence = useSequence()
  const itemIndex = useItemIndex()
  const hasSequence = sequence !== null
  const sequenceStarted = sequence?.sequenceStarted ?? false
  const sequenceActiveIndex = sequence?.activeIndex ?? null
  const sequenceCompleteItemRef = useRef<
    SequenceContextValue["completeItem"] | null
  >(null)
  const sequenceItemIndexRef = useRef<number | null>(null)

  useEffect(() => {
    sequenceCompleteItemRef.current = sequence?.completeItem ?? null
    sequenceItemIndexRef.current = itemIndex
  }, [sequence?.completeItem, itemIndex])

  useEffect(() => {
    let startTimeout: ReturnType<typeof setTimeout> | null = null

    if (hasSequence && itemIndex !== null) {
      if (sequenceStarted && !started && sequenceActiveIndex === itemIndex) {
        setStarted(true)
      }
    } else if (!startOnView || isInView) {
      startTimeout = setTimeout(() => setStarted(true), delay)
    }

    return () => {
      if (startTimeout !== null) {
        clearTimeout(startTimeout)
      }
    }
  }, [
    delay,
    startOnView,
    isInView,
    started,
    hasSequence,
    sequenceActiveIndex,
    sequenceStarted,
    itemIndex,
  ])

  useEffect(() => {
    let typingEffect: ReturnType<typeof setInterval> | null = null

    if (started) {
      let i = 0
      typingEffect = setInterval(() => {
        if (i < children.length) {
          setDisplayedText(children.substring(0, i + 1))
          i++
        } else {
          if (typingEffect !== null) {
            clearInterval(typingEffect)
          }
          const completeItem = sequenceCompleteItemRef.current
          const currentItemIndex = sequenceItemIndexRef.current
          if (completeItem && currentItemIndex !== null) {
            completeItem(currentItemIndex)
          }
        }
      }, duration)
    }

    return () => {
      if (typingEffect !== null) {
        clearInterval(typingEffect)
      }
    }
  }, [children, duration, started])

  return (
    <MotionComponent
      ref={elementRef}
      className={cn("text-sm font-normal tracking-tight", className)}
      {...props}
    >
      {displayedText}
    </MotionComponent>
  )
}

interface TerminalProps {
  children: React.ReactNode
  className?: string
  sequence?: boolean
  startOnView?: boolean
}

export const Terminal = ({
  children,
  className,
  sequence = true,
  startOnView = true,
}: TerminalProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const isInView = useInView(containerRef as React.RefObject<Element>, {
    amount: 0.3,
    once: true,
  })

  const [activeIndex, setActiveIndex] = useState(0)
  const sequenceHasStarted = sequence ? !startOnView || isInView : false

  const contextValue = useMemo<SequenceContextValue | null>(() => {
    if (!sequence) return null
    return {
      completeItem: (index: number) => {
        setActiveIndex((current) => (index === current ? current + 1 : current))
      },
      activeIndex,
      sequenceStarted: sequenceHasStarted,
    }
  }, [sequence, activeIndex, sequenceHasStarted])

  const wrappedChildren = useMemo(() => {
    if (!sequence) return children
    const array = Children.toArray(children)
    return array.map((child, index) => (
      <ItemIndexContext.Provider key={index} value={index}>
        {child as React.ReactNode}
      </ItemIndexContext.Provider>
    ))
  }, [children, sequence])

  const content = (
    <div
      ref={containerRef}
      className={cn(
        "border-border bg-background z-0 h-full max-h-100 w-full max-w-lg rounded-xl border",
        className
      )}
    >
      <div className="border-border flex flex-col gap-y-2 border-b p-4">
        <div className="flex flex-row gap-x-2">
          <div className="h-2 w-2 rounded-full bg-red-500"></div>
          <div className="h-2 w-2 rounded-full bg-yellow-500"></div>
          <div className="h-2 w-2 rounded-full bg-green-500"></div>
        </div>
      </div>
      <pre className="p-4">
        <code className="grid gap-y-1 overflow-auto">{wrappedChildren}</code>
      </pre>
    </div>
  )

  if (!sequence) return content

  return (
    <SequenceContext.Provider value={contextValue}>
      {content}
    </SequenceContext.Provider>
  )
}

```

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import {
  AnimatedSpan,
  Terminal,
  TypingAnimation,
} from "@/components/ui/terminal"
```

```tsx showLineNumbers
<Terminal>
  <TypingAnimation>pnpm dlx shadcn@latest init</TypingAnimation>
  <AnimatedSpan>✔ Preflight checks.</AnimatedSpan>
  <AnimatedSpan>✔ Validating Tailwind CSS.</AnimatedSpan>
  <TypingAnimation>Success! Project initialization completed.</TypingAnimation>
</Terminal>
```

The terminal sequences its children automatically. Each `TypingAnimation` or `AnimatedSpan` starts when the previous finishes. Manual `delay` props are optional and typically unnecessary.

## Props

### Terminal

| Prop          | Type        | Default | Description                                                    |
| ------------- | ----------- | ------- | -------------------------------------------------------------- |
| `children`    | `ReactNode` | `-`     | Terminal content: a list of `TypingAnimation`/`AnimatedSpan`.  |
| `className`   | `string`    | `-`     | Custom CSS class for styling.                                  |
| `sequence`    | `boolean`   | `true`  | Enable auto sequencing so each line starts after the previous. |
| `startOnView` | `boolean`   | `true`  | Start sequencing when the terminal enters the viewport.        |

### AnimatedSpan

| Prop          | Type        | Default | Description                                                                 |
| ------------- | ----------- | ------- | --------------------------------------------------------------------------- |
| `children`    | `ReactNode` | `-`     | Content to be faded in.                                                     |
| `className`   | `string`    | `-`     | Custom CSS class for styling.                                               |
| `delay`       | `number`    | `0`     | Delay in ms before animation starts (used when `sequence` is `false`).      |
| `startOnView` | `boolean`   | `false` | If `true`, waits for viewport visibility before animating when unsequenced. |

### TypingAnimation

| Prop          | Type                                                                                                       | Default  | Description                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------ |
| `children`    | `string`                                                                                                   | `-`      | Text to be typed.                                                        |
| `className`   | `string`                                                                                                   | `-`      | Custom CSS class for styling.                                            |
| `duration`    | `number`                                                                                                   | `60`     | Milliseconds per character.                                              |
| `delay`       | `number`                                                                                                   | `0`      | Delay in ms before typing starts (used when `sequence` is `false`).      |
| `as`          | `"article" \| "div" \| "h1" \| "h2" \| "h3" \| "h4" \| "h5" \| "h6" \| "li" \| "p" \| "section" \| "span"` | `"span"` | The component type to render.                                            |
| `startOnView` | `boolean`                                                                                                  | `true`   | If `true`, waits for viewport visibility before typing when unsequenced. |


Link Beam:

---
title: Animated Beam
date: 2024-02-11
description: An animated beam of light which travels along a path. Useful for showcasing the "integration" features of a website.
author: dillionverma
published: true
video: https://cdn.magicui.design/animated-beam.mp4
---

<ComponentPreview name="animated-beam-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/animated-beam
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import { useEffect, useId, useState, type RefObject } from "react"
import { motion } from "motion/react"

import { cn } from "@/lib/utils"

export interface AnimatedBeamProps {
  className?: string
  containerRef: RefObject<HTMLElement | null> // Container ref
  fromRef: RefObject<HTMLElement | null>
  toRef: RefObject<HTMLElement | null>
  curvature?: number
  reverse?: boolean
  pathColor?: string
  pathWidth?: number
  pathOpacity?: number
  gradientStartColor?: string
  gradientStopColor?: string
  delay?: number
  duration?: number
  repeat?: number
  repeatDelay?: number
  startXOffset?: number
  startYOffset?: number
  endXOffset?: number
  endYOffset?: number
}

export const AnimatedBeam: React.FC<AnimatedBeamProps> = ({
  className,
  containerRef,
  fromRef,
  toRef,
  curvature = 0,
  reverse = false, // Include the reverse prop
  duration = 5,
  delay = 0,
  pathColor = "gray",
  pathWidth = 2,
  pathOpacity = 0.2,
  gradientStartColor = "#ffaa40",
  gradientStopColor = "#9c40ff",
  repeat = Infinity,
  repeatDelay = 0,
  startXOffset = 0,
  startYOffset = 0,
  endXOffset = 0,
  endYOffset = 0,
}) => {
  const id = useId()
  const [pathD, setPathD] = useState("")
  const [svgDimensions, setSvgDimensions] = useState({ width: 0, height: 0 })

  // Calculate the gradient coordinates based on the reverse prop
  const gradientCoordinates = reverse
    ? {
        x1: ["90%", "-10%"],
        x2: ["100%", "0%"],
        y1: ["0%", "0%"],
        y2: ["0%", "0%"],
      }
    : {
        x1: ["10%", "110%"],
        x2: ["0%", "100%"],
        y1: ["0%", "0%"],
        y2: ["0%", "0%"],
      }

  useEffect(() => {
    const updatePath = () => {
      if (containerRef.current && fromRef.current && toRef.current) {
        const containerRect = containerRef.current.getBoundingClientRect()
        const rectA = fromRef.current.getBoundingClientRect()
        const rectB = toRef.current.getBoundingClientRect()

        const svgWidth = containerRect.width
        const svgHeight = containerRect.height
        setSvgDimensions({ width: svgWidth, height: svgHeight })

        const startX =
          rectA.left - containerRect.left + rectA.width / 2 + startXOffset
        const startY =
          rectA.top - containerRect.top + rectA.height / 2 + startYOffset
        const endX =
          rectB.left - containerRect.left + rectB.width / 2 + endXOffset
        const endY =
          rectB.top - containerRect.top + rectB.height / 2 + endYOffset

        const controlY = startY - curvature
        const d = `M ${startX},${startY} Q ${
          (startX + endX) / 2
        },${controlY} ${endX},${endY}`
        setPathD(d)
      }
    }

    // Initialize ResizeObserver
    const resizeObserver = new ResizeObserver(() => {
      updatePath()
    })

    // Observe the container element
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current)
    }

    // Call the updatePath initially to set the initial path
    updatePath()

    // Clean up the observer on component unmount
    return () => {
      resizeObserver.disconnect()
    }
  }, [
    containerRef,
    fromRef,
    toRef,
    curvature,
    startXOffset,
    startYOffset,
    endXOffset,
    endYOffset,
  ])

  return (
    <svg
      fill="none"
      width={svgDimensions.width}
      height={svgDimensions.height}
      xmlns="http://www.w3.org/2000/svg"
      className={cn(
        "pointer-events-none absolute top-0 left-0 transform-gpu stroke-2",
        className
      )}
      viewBox={`0 0 ${svgDimensions.width} ${svgDimensions.height}`}
    >
      <path
        d={pathD}
        stroke={pathColor}
        strokeWidth={pathWidth}
        strokeOpacity={pathOpacity}
        strokeLinecap="round"
      />
      <path
        d={pathD}
        strokeWidth={pathWidth}
        stroke={`url(#${id})`}
        strokeOpacity="1"
        strokeLinecap="round"
      />
      <defs>
        <motion.linearGradient
          className="transform-gpu"
          id={id}
          gradientUnits={"userSpaceOnUse"}
          initial={{
            x1: "0%",
            x2: "0%",
            y1: "0%",
            y2: "0%",
          }}
          animate={{
            x1: gradientCoordinates.x1,
            x2: gradientCoordinates.x2,
            y1: gradientCoordinates.y1,
            y2: gradientCoordinates.y2,
          }}
          transition={{
            delay,
            duration,
            ease: [0.16, 1, 0.3, 1], // https://easings.net/#easeOutExpo
            repeat,
            repeatDelay,
          }}
        >
          <stop stopColor={gradientStartColor} stopOpacity="0"></stop>
          <stop stopColor={gradientStartColor}></stop>
          <stop offset="32.5%" stopColor={gradientStopColor}></stop>
          <stop
            offset="100%"
            stopColor={gradientStopColor}
            stopOpacity="0"
          ></stop>
        </motion.linearGradient>
      </defs>
    </svg>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Examples

### Animated Beam Uni-Directional

<ComponentPreview name="animated-beam-unidirectional" />

### Animated Beam Bi-Directional

<ComponentPreview name="animated-beam-bidirectional" />

### Animated Beam Multiple Inputs

<ComponentPreview name="animated-beam-multiple-inputs" />

### Animated Beam Multiple Outputs

<ComponentPreview name="animated-beam-multiple-outputs" />

## Usage

```tsx showLineNumbers
import { AnimatedBeam } from "@/components/ui/animated-beam"
```

```tsx showLineNumbers
<AnimatedBeam containerRef={containerRef} fromRef={fromRef} toRef={toRef} />
```

## Props

### Animated Beam

| Prop                 | Type      | Default    | Description                                              |
| -------------------- | --------- | ---------- | -------------------------------------------------------- |
| `className`          | `string`  | `-`        | The class name for the component.                        |
| `containerRef`       | `ref`     | `-`        | The container ref.                                       |
| `fromRef`            | `ref`     | `-`        | The ref of the element from which the beam should start. |
| `toRef`              | `ref`     | `-`        | The ref of the element to which the beam should end.     |
| `curvature`          | `number`  | `0`        | The curvature of the beam.                               |
| `reverse`            | `boolean` | `false`    | Whether the beam should be reversed.                     |
| `duration`           | `number`  | `5`        | The duration of the beam.                                |
| `delay`              | `number`  | `0`        | The delay of the beam.                                   |
| `repeat`             | `number`  | `Infinity` | The number of times the beam animation should repeat.    |
| `repeatDelay`        | `number`  | `0`        | The delay between repeated beam animation cycles.        |
| `pathColor`          | `string`  | `gray`     | The color of the beam.                                   |
| `pathWidth`          | `number`  | `2`        | The width of the beam.                                   |
| `pathOpacity`        | `number`  | `0.2`      | The opacity of the beam.                                 |
| `gradientStartColor` | `string`  | `#ffaa40`  | The start color of the gradient.                         |
| `gradientStopColor`  | `string`  | `#9c40ff`  | The stop color of the gradient.                          |
| `startXOffset`       | `number`  | `0`        | The start x offset of the beam.                          |
| `startYOffset`       | `number`  | `0`        | The start y offset of the beam.                          |
| `endXOffset`         | `number`  | `0`        | The end x offset of the beam.                            |
| `endYOffset`         | `number`  | `0`        | The end y offset of the beam.                            |

## Credits

- Credit to [@itsarghyadas](https://twitter.com/itsarghyadas) for figuring out the foundation of this!


Source Number:
---
title: Number Ticker
date: 2023-11-18
description: Animate numbers to count up or down to a target number
author: dillionverma
published: true
video: https://cdn.magicui.design/number-ticker.mp4
---

<ComponentPreview name="number-ticker-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/number-ticker
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import { useEffect, useRef, type ComponentPropsWithoutRef } from "react"
import { useInView, useMotionValue, useSpring } from "motion/react"

import { cn } from "@/lib/utils"

interface NumberTickerProps extends ComponentPropsWithoutRef<"span"> {
  value: number
  startValue?: number
  direction?: "up" | "down"
  delay?: number
  decimalPlaces?: number
}

export function NumberTicker({
  value,
  startValue = 0,
  direction = "up",
  delay = 0,
  className,
  decimalPlaces = 0,
  ...props
}: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const motionValue = useMotionValue(direction === "down" ? value : startValue)
  const springValue = useSpring(motionValue, {
    damping: 60,
    stiffness: 100,
  })
  const isInView = useInView(ref, { once: true, margin: "0px" })

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null

    if (isInView) {
      timer = setTimeout(() => {
        motionValue.set(direction === "down" ? startValue : value)
      }, delay * 1000)
    }

    return () => {
      if (timer !== null) {
        clearTimeout(timer)
      }
    }
  }, [motionValue, isInView, delay, value, direction, startValue])

  useEffect(
    () =>
      springValue.on("change", (latest) => {
        if (ref.current) {
          ref.current.textContent = Intl.NumberFormat("en-US", {
            minimumFractionDigits: decimalPlaces,
            maximumFractionDigits: decimalPlaces,
          }).format(Number(latest.toFixed(decimalPlaces)))
        }
      }),
    [springValue, decimalPlaces]
  )

  return (
    <span
      ref={ref}
      className={cn(
        "inline-block tracking-wider text-black tabular-nums dark:text-white",
        className
      )}
      {...props}
    >
      {startValue}
    </span>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Example

### Decimal

<ComponentPreview name="number-ticker-decimal-demo" />

### Start Value

<ComponentPreview name="number-ticker-demo-2" />

### Usage

```tsx showLineNumbers
import { NumberTicker } from "@/components/ui/number-ticker"
```

```tsx showLineNumbers
<NumberTicker value={100} />
```

## Props

| Prop            | Type         | Default | Description                          |
| --------------- | ------------ | ------- | ------------------------------------ |
| `value`         | `int`        | `0`     | The value to count to                |
| `direction`     | `up \| down` | `"up"`  | The direction to count in            |
| `delay`         | `number`     | `0`     | The delay before counting            |
| `decimalPlaces` | `number`     | `0`     | The number of decimal places to show |
| `startValue`    | `number`     | `0`     | The value to start counting from     |


Speed Scroll:
---
title: Scroll Based Velocity
date: 2024-05-22
description: Scrolling text whose speed changes based on scroll speed
author: whyismynamerudy
published: true
---

<ComponentPreview name="scroll-based-velocity-demo" />

<ComponentPreview name="scroll-based-velocity-images-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/scroll-based-velocity
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Install the following dependencies:</Step>

```bash
npm install motion
```

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import React, { useContext, useEffect, useRef, useState } from "react"
import {
  motion,
  useAnimationFrame,
  useMotionValue,
  useScroll,
  useSpring,
  useTransform,
  useVelocity,
} from "motion/react"
import type { MotionValue } from "motion/react"

import { cn } from "@/lib/utils"

interface ScrollVelocityRowProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  baseVelocity?: number
  direction?: 1 | -1
  scrollReactivity?: boolean
}

export const wrap = (min: number, max: number, v: number) => {
  const rangeSize = max - min
  return ((((v - min) % rangeSize) + rangeSize) % rangeSize) + min
}

const ScrollVelocityContext = React.createContext<MotionValue<number> | null>(
  null
)

export function ScrollVelocityContainer({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  const { scrollY } = useScroll()
  const scrollVelocity = useVelocity(scrollY)
  const smoothVelocity = useSpring(scrollVelocity, {
    damping: 50,
    stiffness: 400,
  })
  const velocityFactor = useTransform(smoothVelocity, (v) => {
    const sign = v < 0 ? -1 : 1
    const magnitude = Math.min(5, (Math.abs(v) / 1000) * 5)
    return sign * magnitude
  })

  return (
    <ScrollVelocityContext.Provider value={velocityFactor}>
      <div className={cn("relative w-full", className)} {...props}>
        {children}
      </div>
    </ScrollVelocityContext.Provider>
  )
}

export function ScrollVelocityRow(props: ScrollVelocityRowProps) {
  const sharedVelocityFactor = useContext(ScrollVelocityContext)
  if (sharedVelocityFactor) {
    return (
      <ScrollVelocityRowImpl {...props} velocityFactor={sharedVelocityFactor} />
    )
  }
  return <ScrollVelocityRowLocal {...props} />
}

interface ScrollVelocityRowImplProps extends ScrollVelocityRowProps {
  velocityFactor: MotionValue<number>
}

function ScrollVelocityRowImpl({
  children,
  baseVelocity = 5,
  direction = 1,
  className,
  velocityFactor,
  scrollReactivity = true,
  ...props
}: ScrollVelocityRowImplProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const blockRef = useRef<HTMLDivElement>(null)
  const [numCopies, setNumCopies] = useState(1)

  const baseX = useMotionValue(0)
  const baseDirectionRef = useRef<number>(direction >= 0 ? 1 : -1)
  const currentDirectionRef = useRef<number>(direction >= 0 ? 1 : -1)
  const unitWidth = useMotionValue(0)

  const isInViewRef = useRef(true)
  const isPageVisibleRef = useRef(true)
  const prefersReducedMotionRef = useRef(false)

  useEffect(() => {
    const container = containerRef.current
    const block = blockRef.current
    let ro: ResizeObserver | null = null
    let io: IntersectionObserver | null = null
    let mq: MediaQueryList | null = null
    const handleVisibility = () => {
      isPageVisibleRef.current = document.visibilityState === "visible"
    }
    const handlePRM = () => {
      if (mq) {
        prefersReducedMotionRef.current = mq.matches
      }
    }

    if (container && block) {
      const updateSizes = () => {
        const cw = container.offsetWidth || 0
        const bw = block.scrollWidth || 0
        unitWidth.set(bw)
        const nextCopies = bw > 0 ? Math.max(3, Math.ceil(cw / bw) + 2) : 1
        setNumCopies((prev) => (prev === nextCopies ? prev : nextCopies))
      }

      updateSizes()

      ro = new ResizeObserver(updateSizes)
      ro.observe(container)
      ro.observe(block)

      io = new IntersectionObserver(([entry]) => {
        isInViewRef.current = entry.isIntersecting
      })
      io.observe(container)

      document.addEventListener("visibilitychange", handleVisibility, {
        passive: true,
      })
      handleVisibility()

      mq = window.matchMedia("(prefers-reduced-motion: reduce)")
      mq.addEventListener("change", handlePRM)
      handlePRM()
    }

    return () => {
      if (ro) {
        ro.disconnect()
      }
      if (io) {
        io.disconnect()
      }
      document.removeEventListener("visibilitychange", handleVisibility)
      if (mq) {
        mq.removeEventListener("change", handlePRM)
      }
    }
  }, [children, unitWidth])

  const x = useTransform([baseX, unitWidth], ([v, bw]) => {
    const width = Number(bw) || 1
    const offset = Number(v) || 0
    return `${-wrap(0, width, offset)}px`
  })

  useAnimationFrame((_, delta) => {
    if (!isInViewRef.current || !isPageVisibleRef.current) return
    const dt = delta / 1000
    const vf = scrollReactivity ? velocityFactor.get() : 0
    const absVf = Math.min(5, Math.abs(vf))
    const speedMultiplier = prefersReducedMotionRef.current ? 1 : 1 + absVf

    if (absVf > 0.1) {
      const scrollDirection = vf >= 0 ? 1 : -1
      currentDirectionRef.current = baseDirectionRef.current * scrollDirection
    }

    const bw = unitWidth.get() || 0
    if (bw <= 0) return
    const pixelsPerSecond = (bw * baseVelocity) / 100
    const moveBy =
      currentDirectionRef.current * pixelsPerSecond * speedMultiplier * dt
    baseX.set(baseX.get() + moveBy)
  })

  return (
    <div
      ref={containerRef}
      className={cn("w-full overflow-hidden whitespace-nowrap", className)}
      {...props}
    >
      <motion.div
        className="inline-flex transform-gpu items-center will-change-transform select-none"
        style={{ x }}
      >
        {Array.from({ length: numCopies }).map((_, i) => (
          <div
            key={i}
            ref={i === 0 ? blockRef : null}
            aria-hidden={i !== 0}
            className="inline-flex shrink-0 items-center"
          >
            {children}
          </div>
        ))}
      </motion.div>
    </div>
  )
}

function ScrollVelocityRowLocal(props: ScrollVelocityRowProps) {
  const { scrollY } = useScroll()
  const localVelocity = useVelocity(scrollY)
  const localSmoothVelocity = useSpring(localVelocity, {
    damping: 50,
    stiffness: 400,
  })
  const localVelocityFactor = useTransform(localSmoothVelocity, (v) => {
    const sign = v < 0 ? -1 : 1
    const magnitude = Math.min(5, (Math.abs(v) / 1000) * 5)
    return sign * magnitude
  })
  return (
    <ScrollVelocityRowImpl {...props} velocityFactor={localVelocityFactor} />
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import {
  ScrollVelocityContainer,
  ScrollVelocityRow,
} from "@/components/ui/scroll-based-velocity"
```

```tsx showLineNumbers
<ScrollVelocityContainer className="text-4xl font-bold md:text-7xl">
  <ScrollVelocityRow baseVelocity={20} direction={1}>
    Velocity Scroll
  </ScrollVelocityRow>
  <ScrollVelocityRow baseVelocity={20} direction={-1}>
    Velocity Scroll
  </ScrollVelocityRow>
</ScrollVelocityContainer>
```

## Props

### ScrollVelocityContainer

| Prop        | Type        | Default | Description                                   |
| ----------- | ----------- | ------- | --------------------------------------------- |
| `className` | `string`    | `-`     | The class name to be applied to the component |
| `children`  | `ReactNode` | `-`     | Content to be animated                        |

### ScrollVelocityRow

| Prop               | Type        | Default | Description                                        |
| ------------------ | ----------- | ------- | -------------------------------------------------- |
| `className`        | `string`    | `-`     | The class name to be applied to the row container  |
| `children`         | `ReactNode` | `-`     | Content to be duplicated and scrolled              |
| `baseVelocity`     | `number`    | `5`     | Base scroll velocity percentage of content width   |
| `direction`        | `1 \| -1`   | `1`     | Scroll direction (1 = left-to-right, -1 = reverse) |
| `scrollReactivity` | `boolean`   | `true`  | Toggles scroll interactivity                       |

## Performance

- Pauses updates when offscreen and when the tab is hidden.
- Respects user preference for reduced motion.


Background Grid:

---
title: Animated Grid Pattern
date: 2024-02-07
description: A animated background grid pattern made with SVGs, fully customizable using Tailwind CSS.
author: dillionverma
published: true
---

<ComponentPreview name="animated-grid-pattern-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/animated-grid-pattern
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
} from "react"
import { motion } from "motion/react"

import { cn } from "@/lib/utils"

export interface AnimatedGridPatternProps extends ComponentPropsWithoutRef<"svg"> {
  width?: number
  height?: number
  x?: number
  y?: number
  strokeDasharray?: number
  numSquares?: number
  maxOpacity?: number
  duration?: number
  repeatDelay?: number
}

type Square = {
  id: number
  pos: [number, number]
  iteration: number
}

export function AnimatedGridPattern({
  width = 40,
  height = 40,
  x = -1,
  y = -1,
  strokeDasharray = 0,
  numSquares = 50,
  className,
  maxOpacity = 0.5,
  duration = 4,
  repeatDelay = 0.5,
  ...props
}: AnimatedGridPatternProps) {
  const id = useId()
  const containerRef = useRef<SVGSVGElement | null>(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [squares, setSquares] = useState<Array<Square>>([])

  const getPos = useCallback((): [number, number] => {
    return [
      Math.floor((Math.random() * dimensions.width) / width),
      Math.floor((Math.random() * dimensions.height) / height),
    ]
  }, [dimensions.height, dimensions.width, height, width])

  const generateSquares = useCallback(
    (count: number) => {
      return Array.from({ length: count }, (_, i) => ({
        id: i,
        pos: getPos(),
        iteration: 0,
      }))
    },
    [getPos]
  )

  const updateSquarePosition = useCallback(
    (squareId: number) => {
      setSquares((currentSquares) => {
        const current = currentSquares[squareId]
        if (!current || current.id !== squareId) return currentSquares

        const nextSquares = currentSquares.slice()
        nextSquares[squareId] = {
          ...current,
          pos: getPos(),
          iteration: current.iteration + 1,
        }

        return nextSquares
      })
    },
    [getPos]
  )

  useEffect(() => {
    if (dimensions.width && dimensions.height) {
      setSquares(generateSquares(numSquares))
    }
  }, [dimensions.width, dimensions.height, generateSquares, numSquares])

  useEffect(() => {
    const element = containerRef.current
    let resizeObserver: ResizeObserver | null = null

    if (element) {
      resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          setDimensions((currentDimensions) => {
            const nextWidth = entry.contentRect.width
            const nextHeight = entry.contentRect.height
            if (
              currentDimensions.width === nextWidth &&
              currentDimensions.height === nextHeight
            ) {
              return currentDimensions
            }
            return { width: nextWidth, height: nextHeight }
          })
        }
      })

      resizeObserver.observe(element)
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect()
      }
    }
  }, [])

  return (
    <svg
      ref={containerRef}
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0 h-full w-full fill-gray-400/30 stroke-gray-400/30",
        className
      )}
      {...props}
    >
      <defs>
        <pattern
          id={id}
          width={width}
          height={height}
          patternUnits="userSpaceOnUse"
          x={x}
          y={y}
        >
          <path
            d={`M.5 ${height}V.5H${width}`}
            fill="none"
            strokeDasharray={strokeDasharray}
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
      <svg x={x} y={y} className="overflow-visible">
        {squares.map(({ pos: [squareX, squareY], id, iteration }, index) => (
          <motion.rect
            initial={{ opacity: 0 }}
            animate={{ opacity: maxOpacity }}
            transition={{
              duration,
              repeat: 1,
              delay: index * 0.1,
              repeatType: "reverse",
              repeatDelay,
            }}
            onAnimationComplete={() => updateSquarePosition(id)}
            key={`${id}-${iteration}`}
            width={width - 1}
            height={height - 1}
            x={squareX * width + 1}
            y={squareY * height + 1}
            fill="currentColor"
            strokeWidth="0"
          />
        ))}
      </svg>
    </svg>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import { AnimatedGridPattern } from "@/components/ui/animated-grid-pattern"
```

```tsx showLineNumbers
<AnimatedGridPattern />
```

## Props

### GridPattern

| Prop              | Type     | Default | Description                                   |
| ----------------- | -------- | ------- | --------------------------------------------- |
| `className`       | `string` | `-`     | Additional classes to be added to the pattern |
| `width`           | `number` | `40`    | Width of the pattern                          |
| `height`          | `number` | `40`    | Height of the pattern                         |
| `x`               | `number` | `-1`    | X offset of the pattern                       |
| `y`               | `number` | `-1`    | Y offset of the pattern                       |
| `strokeDasharray` | `number` | `0`     | Stroke dash array of the pattern              |
| `numSquares`      | `number` | `200`   | Number of squares in the pattern              |
| `maxOpacity`      | `number` | `0.5`   | Maximum opacity of the pattern                |
| `duration`        | `number` | `1`     | Duration of the animation                     |
| `repeatDelay`     | `number` | `0.5`   | Repeat delay of the animation                 |


Loading Bar:
---
title: Animated Circular Progress Bar
date: 2024-05-28
description: Animated Circular Progress Bar is a component that displays a circular gauge with a percentage value.
author: luis-codex
published: true
---

<ComponentPreview name="animated-circular-progress-bar-demo" />

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/animated-circular-progress-bar
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
import { cn } from "@/lib/utils"

interface AnimatedCircularProgressBarProps {
  max?: number
  min?: number
  value: number
  gaugePrimaryColor: string
  gaugeSecondaryColor: string
  className?: string
}

export function AnimatedCircularProgressBar({
  max = 100,
  min = 0,
  value = 0,
  gaugePrimaryColor,
  gaugeSecondaryColor,
  className,
}: AnimatedCircularProgressBarProps) {
  const circumference = 2 * Math.PI * 45
  const percentPx = circumference / 100
  const currentPercent = Math.round(((value - min) / (max - min)) * 100)

  return (
    <div
      className={cn("relative size-40 text-2xl font-semibold", className)}
      style={
        {
          "--circle-size": "100px",
          "--circumference": circumference,
          "--percent-to-px": `${percentPx}px`,
          "--gap-percent": "5",
          "--offset-factor": "0",
          "--transition-length": "1s",
          "--transition-step": "200ms",
          "--delay": "0s",
          "--percent-to-deg": "3.6deg",
          transform: "translateZ(0)",
        } as React.CSSProperties
      }
    >
      <svg
        fill="none"
        className="size-full"
        strokeWidth="2"
        viewBox="0 0 100 100"
      >
        {currentPercent <= 90 && currentPercent >= 0 && (
          <circle
            cx="50"
            cy="50"
            r="45"
            strokeWidth="10"
            strokeDashoffset="0"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-100"
            style={
              {
                stroke: gaugeSecondaryColor,
                "--stroke-percent": 90 - currentPercent,
                "--offset-factor-secondary": "calc(1 - var(--offset-factor))",
                strokeDasharray:
                  "calc(var(--stroke-percent) * var(--percent-to-px)) var(--circumference)",
                transform:
                  "rotate(calc(1turn - 90deg - (var(--gap-percent) * var(--percent-to-deg) * var(--offset-factor-secondary)))) scaleY(-1)",
                transition: "all var(--transition-length) ease var(--delay)",
                transformOrigin:
                  "calc(var(--circle-size) / 2) calc(var(--circle-size) / 2)",
              } as React.CSSProperties
            }
          />
        )}
        <circle
          cx="50"
          cy="50"
          r="45"
          strokeWidth="10"
          strokeDashoffset="0"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="opacity-100"
          style={
            {
              stroke: gaugePrimaryColor,
              "--stroke-percent": currentPercent,
              strokeDasharray:
                "calc(var(--stroke-percent) * var(--percent-to-px)) var(--circumference)",
              transition:
                "var(--transition-length) ease var(--delay),stroke var(--transition-length) ease var(--delay)",
              transitionProperty: "stroke-dasharray,transform",
              transform:
                "rotate(calc(-90deg + var(--gap-percent) * var(--offset-factor) * var(--percent-to-deg)))",
              transformOrigin:
                "calc(var(--circle-size) / 2) calc(var(--circle-size) / 2)",
            } as React.CSSProperties
          }
        />
      </svg>
      <span
        data-current-value={currentPercent}
        className="animate-in fade-in absolute inset-0 m-auto size-fit delay-(--delay) duration-(--transition-length) ease-linear"
      >
        {currentPercent}
      </span>
    </div>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import { AnimatedCircularProgressBar } from "@/components/ui/animated-circular-progress-bar"
```

```tsx showLineNumbers
<AnimatedCircularProgressBar />
```

## Props

| Prop                  | Type     | Default | Description                                   |
| --------------------- | -------- | ------- | --------------------------------------------- |
| `className`           | `string` | `-`     | The class name to be applied to the component |
| `max`                 | `number` | `100`   | The maximum value of the gauge                |
| `min`                 | `number` | `0`     | The minimum value of the gauge                |
| `value`               | `number` | `0`     | The current value of the gauge                |
| `gaugePrimaryColor`   | `string` | `-`     | The primary color of the gauge                |
| `gaugeSecondaryColor` | `string` | `-`     | The secondary color of the gauge              |

## Credits

- Credit to [@luis-code](https://luis-code.vercel.app/)


Pixel Image:
---
title: Pixel Image
date: 2025-06-05
description: A component that displays your image with a pixelated effect, enhancing the visual appeal of any image in your website.
author: dharminnagar
published: true
---

<ComponentPreview name="pixel-image-demo" />

## Features

- Pixelated image reveal animation
- Customizable grid size and layout
- Supports grayscale-to-color animation
- Adjustable animation duration and delay
- Lightweight and easy to use

## Installation

<Tabs defaultValue="cli">

<TabsList>
  <TabsTrigger value="cli">CLI</TabsTrigger>
  <TabsTrigger value="manual">Manual</TabsTrigger>
</TabsList>
<TabsContent value="cli">

```bash
npx shadcn@latest add @magicui/pixel-image
```

</TabsContent>

<TabsContent value="manual">

<Steps>

<Step>Copy and paste the following code into your project.</Step>

```tsx
"use client"

import { useEffect, useMemo, useState } from "react"

import { cn } from "@/lib/utils"

type Grid = {
  rows: number
  cols: number
}

const DEFAULT_GRIDS: Record<string, Grid> = {
  "6x4": { rows: 4, cols: 6 },
  "8x8": { rows: 8, cols: 8 },
  "8x3": { rows: 3, cols: 8 },
  "4x6": { rows: 6, cols: 4 },
  "3x8": { rows: 8, cols: 3 },
}

type PredefinedGridKey = keyof typeof DEFAULT_GRIDS

interface PixelImageProps {
  src: string
  grid?: PredefinedGridKey
  customGrid?: Grid
  grayscaleAnimation?: boolean
  pixelFadeInDuration?: number // in ms
  maxAnimationDelay?: number // in ms
  colorRevealDelay?: number // in ms
}

export const PixelImage = ({
  src,
  grid = "6x4",
  grayscaleAnimation = true,
  pixelFadeInDuration = 1000,
  maxAnimationDelay = 1200,
  colorRevealDelay = 1300,
  customGrid,
}: PixelImageProps) => {
  const [isVisible, setIsVisible] = useState(false)
  const [showColor, setShowColor] = useState(false)

  const MIN_GRID = 1
  const MAX_GRID = 16

  const { rows, cols } = useMemo(() => {
    const isValidGrid = (grid?: Grid) => {
      if (!grid) return false
      const { rows, cols } = grid
      return (
        Number.isInteger(rows) &&
        Number.isInteger(cols) &&
        rows >= MIN_GRID &&
        cols >= MIN_GRID &&
        rows <= MAX_GRID &&
        cols <= MAX_GRID
      )
    }

    return isValidGrid(customGrid) ? customGrid! : DEFAULT_GRIDS[grid]
  }, [customGrid, grid])

  useEffect(() => {
    setIsVisible(true)
    const colorTimeout = setTimeout(() => {
      setShowColor(true)
    }, colorRevealDelay)
    return () => clearTimeout(colorTimeout)
  }, [colorRevealDelay])

  const pieces = useMemo(() => {
    const total = rows * cols
    return Array.from({ length: total }, (_, index) => {
      const row = Math.floor(index / cols)
      const col = index % cols

      const clipPath = `polygon(
        ${col * (100 / cols)}% ${row * (100 / rows)}%,
        ${(col + 1) * (100 / cols)}% ${row * (100 / rows)}%,
        ${(col + 1) * (100 / cols)}% ${(row + 1) * (100 / rows)}%,
        ${col * (100 / cols)}% ${(row + 1) * (100 / rows)}%
      )`

      const delay = Math.random() * maxAnimationDelay
      return {
        clipPath,
        delay,
      }
    })
  }, [rows, cols, maxAnimationDelay])

  return (
    <div className="relative h-72 w-72 select-none md:h-96 md:w-96">
      {pieces.map((piece, index) => (
        <div
          key={index}
          className={cn(
            "absolute inset-0 transition-all ease-out",
            isVisible ? "opacity-100" : "opacity-0"
          )}
          style={{
            clipPath: piece.clipPath,
            transitionDelay: `${piece.delay}ms`,
            transitionDuration: `${pixelFadeInDuration}ms`,
          }}
        >
          <img
            src={src}
            alt={`Pixel image piece ${index + 1}`}
            className={cn(
              "z-1 rounded-[2.5rem] object-cover",
              grayscaleAnimation && (showColor ? "grayscale-0" : "grayscale")
            )}
            style={{
              transition: grayscaleAnimation
                ? `filter ${pixelFadeInDuration}ms cubic-bezier(0.4, 0, 0.2, 1)`
                : "none",
            }}
            draggable={false}
          />
        </div>
      ))}
    </div>
  )
}

```

<Step>Update the import paths to match your project setup.</Step>

</Steps>

</TabsContent>

</Tabs>

## Usage

```tsx showLineNumbers
import { PixelImage } from "@/components/ui/pixel-image"
```

```tsx showLineNumbers
<PixelImage src="/pixel-image-demo.jpg" grid="8x8" />
```

## Props

| Prop                  | Type                                        | Default | Description                                    |
| --------------------- | ------------------------------------------- | ------- | ---------------------------------------------- |
| `src`                 | `string`                                    | —       | The image source URL                           |
| `grid`                | `"6x4" \| "8x8" \| "8x3" \| "4x6" \| "3x8"` | `"8x8"` | Predefined grid layout                         |
| `customGrid`          | `{ rows: number; cols: number; }`           | —       | Custom grid layout (overrides `grid`)          |
| `grayscaleAnimation`  | `boolean`                                   | `true`  | Whether to animate from grayscale to color     |
| `pixelFadeInDuration` | `number`                                    | `1000`  | Duration (ms) for each pixel fade-in animation |
| `maxAnimationDelay`   | `number`                                    | `1200`  | Maximum random delay (ms) for pixel animation  |
| `colorRevealDelay`    | `number`                                    | `1500`  | Delay (ms) before revealing color              |

### Grid Type

```typescript
// Predefined grid options
"6x4" | "8x8" | "8x3" | "4x6" | "3x8"

// Custom grid example
customGrid={{ rows: 5, cols: 10 }}
```

## Note

- Since the pixelation effect is purely decorative, make sure to provide text alternatives (like descriptions or labels) for any important content shown in the image. This ensures the content is accessible to screen reader users.

## Credits

- Credit to [@dharminnagar](https://x.com/dharminnagar) for implementation
