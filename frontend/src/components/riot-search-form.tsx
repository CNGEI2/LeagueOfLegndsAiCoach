"use client";

import { type FormEvent, useState } from "react";

import type { Messages } from "@/i18n/messages";

export function RiotSearchForm({ messages }: { messages: Messages }) {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <form onSubmit={handleSubmit} className="search-card">
      <label>
        <span>{messages.gameName}</span>
        <input name="gameName" autoComplete="off" required maxLength={16} />
      </label>
      <label>
        <span>{messages.tagLine}</span>
        <input name="tagLine" autoComplete="off" required maxLength={5} />
      </label>
      <label>
        <span>{messages.region}</span>
        <select name="platform" defaultValue="NA1">
          <option value="NA1">{messages.northAmerica}</option>
        </select>
      </label>
      <button type="submit">{messages.search}</button>
      <p className="example">{messages.example}</p>
      {submitted ? <p role="status">{messages.phaseNotice}</p> : null}
    </form>
  );
}
