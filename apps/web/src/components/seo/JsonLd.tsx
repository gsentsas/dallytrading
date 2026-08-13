import type { JsonLdObject } from '@/lib/seo';

/**
 * Emit JSON-LD structured data.
 *
 * `dangerouslySetInnerHTML` is required — React escapes text nodes, which would
 * break the JSON. It is safe here because the input is a typed object we build
 * ourselves and serialise with `JSON.stringify`: no user input reaches it.
 *
 * The `<` escaping guards the one remaining hazard: a string containing `</script>`
 * would otherwise close the tag early and turn data into markup. Nothing in the
 * current inputs contains it, but this is the kind of assumption that stops being
 * true when someone pastes copy into a config file.
 */
export function JsonLd({ data }: { data: JsonLdObject | ReadonlyArray<JsonLdObject> }) {
  const payload = Array.isArray(data) ? data : [data];

  return (
    <>
      {payload.map((entry, index) => (
        <script
          key={index}
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(entry).replace(/</g, '\\u003c'),
          }}
        />
      ))}
    </>
  );
}
