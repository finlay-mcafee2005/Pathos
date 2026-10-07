import { useEffect, useState } from "react";

type Slide = {
  src: string;
  // where to anchor the crop, so the subject stays in frame on a tall panel
  position?: string;
};

const SLIDES: Slide[] = [
  { src: "/images/santa-monica-bike-path.jpg", position: "center 60%" },
  { src: "/images/griffith-observatory.jpg", position: "42% center" },
  { src: "/images/runyon-canyon-view.jpg", position: "center" },
  { src: "/images/hillside-trail.jpg" },
];

function BackgroundSlideshow() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((prev) => (prev + 1) % SLIDES.length);
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // keep the index in range even if the slide list changes while the page is open
  const active = index % SLIDES.length;

  return (
    <div className="bg-slideshow">
      {SLIDES.map((slide, i) => (
        <div
          key={slide.src}
          className={`bg-slide ${i === active ? "active" : ""}`}
          style={{ backgroundImage: `url(${slide.src})`, backgroundPosition: slide.position ?? "center" }}
        />
      ))}
      <div className="bg-slideshow-overlay" />
    </div>
  );
}

export default BackgroundSlideshow;
