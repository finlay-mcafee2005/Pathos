import { useEffect, useState } from "react";

const IMAGES = [
  "/images/hollywood-sunset.jpg",
  "/images/hillside-trail.jpg",
  "/images/dusk-runner.jpg",
  "/images/running-lake.jpg",
  "/images/santa-monica-beach.jpg",
];

function BackgroundSlideshow() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((prev) => (prev + 1) % IMAGES.length);
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-slideshow">
      {IMAGES.map((src, i) => (
        <div
          key={src}
          className={`bg-slide ${i === index ? "active" : ""}`}
          style={{ backgroundImage: `url(${src})` }}
        />
      ))}
      <div className="bg-slideshow-overlay" />
    </div>
  );
}

export default BackgroundSlideshow;