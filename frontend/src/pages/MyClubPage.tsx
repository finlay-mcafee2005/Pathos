import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";

type ClubSchedule = {
  day: string;
  time: string;
};

type Club = {
  id: string;
  name: string;
  location: string;
  pace_range: string;
  experience_level: string;
  schedule: ClubSchedule[];
};

function MyClubPage() {
  const userId = localStorage.getItem("user_id");
  const [club, setClub] = useState<Club | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) {
      setError("No user found. Please log in again.");
      setLoading(false);
      return;
    }
    fetch(`${API_URL}/clubs/mine/${userId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then((data) => setClub(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [userId]);

  return (
    <div className="app">
      <header className="header">
        <h1>My club</h1>
      </header>

      {loading && <p>Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {!loading && !error && !club && (
        <p>
          You haven't joined a club yet. Enter a club join code next time you sign up,
          or ask your club for their code.
        </p>
      )}

      {club && (
        <div className="route-card">
          <div className="route-card-header">
            <h2>{club.name}</h2>
          </div>
          <div className="route-stats">
            <span>{club.location}</span>
            <span>{club.pace_range}</span>
            <span className="difficulty">{club.experience_level}</span>
          </div>
          <ul className="reasons">
            {club.schedule.map((s, i) => (
              <li key={i}>
                {s.day.charAt(0).toUpperCase() + s.day.slice(1)} at {s.time}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default MyClubPage;
