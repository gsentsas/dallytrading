/**
 * Le véhicule transporté, tel qu'il est présenté au client.
 *
 * ## Un seul composant pour deux pages
 *
 * Le devis et l'expédition affichent le même véhicule. Deux composants
 * finiraient par diverger — l'un montrerait un champ que l'autre cache — et
 * c'est le moins relu qui exposerait un jour ce qu'il ne devait pas.
 *
 * ## Il ne décide de rien
 *
 * Aucun fetch, aucun identifiant, aucune logique d'autorisation. Il reçoit un
 * DTO déjà filtré par le serveur et se contente de le disposer. L'autorisation
 * vit dans Odoo et dans le BFF ; la reproduire ici créerait un second endroit
 * où se tromper.
 *
 * ## Le VIN
 *
 * Affiché en entier, et volontairement. Ces deux pages sont privées et
 * réservées au propriétaire authentifié, et le VIN est le seul numéro qui
 * distingue deux voitures identiques. Ce composant ne doit donc jamais être
 * réutilisé dans une liste ni dans le suivi public.
 */

import type { PortalVehicle } from '@/lib/portal/dto';

/** Une ligne du tableau, omise quand la valeur est absente. */
function Ligne({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-sm text-mist-600">{label}</dt>
      <dd className="mt-1 text-navy-800">{value}</dd>
    </div>
  );
}

export function VehicleDetails({
  vehicle,
  title = 'Véhicule',
}: {
  vehicle: PortalVehicle;
  title?: string;
}) {
  const designation = [vehicle.make, vehicle.model]
    .filter(Boolean)
    .join(' ');

  return (
    <section aria-labelledby="vehicule" className="mb-6">
      <h2 id="vehicule" className="mb-4 text-lg font-semibold text-navy-800">
        {title}
      </h2>
      <div className="rounded-2xl border border-mist-200 bg-white p-6">
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Ligne label="Véhicule" value={designation || null} />
          <Ligne label="Année" value={vehicle.year} />
          <Ligne label="Numéro de châssis (VIN)" value={vehicle.vin} />
          <Ligne label="Immatriculation" value={vehicle.registration} />
          <Ligne label="Couleur" value={vehicle.color} />
          {/*
            Les libellés viennent du serveur, déjà traduits. Les recalculer ici
            à partir des codes créerait une seconde table de correspondance à
            tenir d'accord avec celle d'Odoo.
          */}
          <Ligne label="Type" value={vehicle.categoryLabel} />
          <Ligne label="État" value={vehicle.conditionLabel} />
          <Ligne label="Motorisation" value={vehicle.fuelTypeLabel} />
          <Ligne
            label="Nombre de clés"
            value={vehicle.keyCount > 0 ? String(vehicle.keyCount) : null}
          />
          <Ligne label="Mode de transport" value={vehicle.transportModeLabel} />
        </dl>

        {/*
          Enlèvement et livraison ne s'affichent que s'ils sont demandés. Une
          ligne « Enlèvement : non » n'apprend rien, et une adresse résiduelle
          ferait croire à une prestation qui n'aura pas lieu.
        */}
        {(vehicle.pickupRequested || vehicle.deliveryRequested) && (
          <dl className="mt-6 grid gap-4 border-t border-mist-200 pt-6 sm:grid-cols-2">
            {vehicle.pickupRequested && (
              <Ligne
                label="Enlèvement demandé"
                value={vehicle.pickupAddress ?? 'Adresse à préciser'}
              />
            )}
            {vehicle.deliveryRequested && (
              <Ligne
                label="Livraison demandée"
                value={vehicle.deliveryAddress ?? 'Adresse à préciser'}
              />
            )}
          </dl>
        )}
      </div>
    </section>
  );
}
