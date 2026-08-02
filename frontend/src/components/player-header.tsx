import type { PlayerProfile } from "@/api/schemas";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";
import { platformDisplayName } from "@/i18n/platform-names";

function fill(template: string, values: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

export function PlayerHeader({
  player,
  messages,
  locale,
}: {
  player: PlayerProfile;
  messages: Messages;
  locale: Locale;
}) {
  const riotId = `${player.game_name}#${player.tag_line}`;

  return (
    <header className="player-header">
      <div className="player-profile-asset">
        {player.profile_icon ? (
          /* The backend supplies a localized public static-data URL; no fixed Next image host is safe here. */
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={player.profile_icon.image_url}
            alt={fill(messages.profileIconAlt, { name: player.game_name })}
          />
        ) : (
          <span aria-hidden="true" className="profile-icon-fallback" />
        )}
      </div>
      <div>
        <p className="eyebrow">{platformDisplayName(locale, player.platform)}</p>
        <h1>{riotId}</h1>
        <p className="utility-data">
          {fill(messages.summonerLevel, { level: player.summoner_level })}
        </p>
      </div>
      {!player.profile_static_data_status.available ? (
        <p className="static-data-warning" role="alert">{messages.staticDataUnavailable}</p>
      ) : null}
    </header>
  );
}
