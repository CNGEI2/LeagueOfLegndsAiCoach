import type { HydratedParticipant } from "@/api/schemas";
import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

function numeric(value: number | null, messages: Messages) {
  return value === null ? messages.unknownStatistic : String(value);
}

function kda(participant: HydratedParticipant, messages: Messages) {
  if (participant.kills === null || participant.deaths === null || participant.assists === null) {
    return messages.unknownStatistic;
  }
  return `${participant.kills} / ${participant.deaths} / ${participant.assists}`;
}

export function MatchTeamTable({
  caption,
  participants,
  selectedPuuid,
  staticDataAvailable,
  messages,
}: {
  caption: string;
  participants: HydratedParticipant[];
  selectedPuuid: string;
  staticDataAvailable: boolean;
  messages: Messages;
}) {
  return (
    <section className="team-table-region" aria-label={caption} tabIndex={0}>
      <table className="team-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{messages.playerIdentity}</th>
            <th scope="col">{messages.champion}</th>
            <th scope="col">{messages.role}</th>
            <th scope="col">{messages.kda}</th>
            <th scope="col">{messages.cs}</th>
            <th scope="col">{messages.gold}</th>
            <th scope="col">{messages.damage}</th>
            <th scope="col">{messages.vision}</th>
            <th scope="col">{messages.item}</th>
          </tr>
        </thead>
        <tbody>
          {participants.map((participant) => {
            const selected = participant.puuid === selectedPuuid;
            return (
              <tr key={participant.puuid} data-selected={selected || undefined} aria-current={selected ? "true" : undefined}>
                <th scope="row">
                  {selected ? <span className="selected-player-label">{messages.selectedPlayer}</span> : participant.puuid}
                </th>
                <td>
                  {staticDataAvailable && participant.champion ? (
                    <span className="asset-with-label">
                      {/* The API hydrates this localized public URL. */}
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={participant.champion.image_url} alt={fill(messages.championAlt, { name: participant.champion.name })} />
                      <span>{participant.champion.name}</span>
                    </span>
                  ) : (
                    `${messages.champion} #${participant.champion_id}`
                  )}
                </td>
                <td>{participant.role ?? messages.unknownStatistic}</td>
                <td>{kda(participant, messages)}</td>
                <td>{numeric(participant.cs, messages)}</td>
                <td>{numeric(participant.gold_earned, messages)}</td>
                <td>{numeric(participant.damage_to_champions, messages)}</td>
                <td>{numeric(participant.vision_score, messages)}</td>
                <td>
                  <ul className="team-item-assets" aria-label={messages.item}>
                    {participant.item_ids.map((itemId, index) => {
                      const item = participant.items[index];
                      return (
                        <li key={`${itemId}-${index}`}>
                          {staticDataAvailable && item ? (
                            <>
                              {/* The API hydrates this localized public URL. */}
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img src={item.image_url} alt={fill(messages.itemAlt, { name: item.name })} />
                              <span className="sr-only">{item.name}</span>
                            </>
                          ) : (
                            `${messages.item} #${itemId}`
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
