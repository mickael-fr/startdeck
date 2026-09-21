# Activer la synchronisation de StartDeck

La nouvelle page fonctionne immédiatement avec les données déjà présentes dans le navigateur.
**Sans activation ci-dessous, les notes, favoris et tâches restent sur chaque appareil.**
GitHub Pages héberge l'application ; Supabase conserve les données privées.

## Une seule fois

1. Créer un projet sur https://supabase.com/dashboard dans votre compte personnel.
2. Ouvrir son **SQL Editor**, coller le contenu de [supabase-setup.sql](./supabase-setup.sql) et exécuter.
3. Dans **Authentication → Users → Add user**, créer votre utilisateur avec votre e-mail et un mot de passe personnel (confirmer l'utilisateur dans cette interface).
4. Dans les paramètres du projet, relever l'URL `https://…supabase.co` et la clé **publishable** (ou l'ancienne clé **anon**). Ne jamais utiliser une clé **secret** ou **service_role** dans StartDeck.
5. Ouvrir StartDeck sur l'appareil contenant les données à conserver. Cliquer **Synchronisation**, exporter d'abord une sauvegarde, remplir les champs puis **Se connecter**.
6. Sur les autres appareils, renseigner le même projet, la même clé publique et le même compte. S'ils contiennent déjà des changements différents, StartDeck demandera quelle version conserver.

L'URL et la clé publique peuvent être renseignées une fois dans `DEFAULT_CLOUD` dans `index.html`, puis publiées. L'e-mail, le mot de passe et les sessions ne doivent jamais être ajoutés au dépôt. Le mot de passe n'est pas conservé par la page ; la session de connexion reste dans le navigateur jusqu'à la déconnexion.

## Fonctionnement

- Sauvegarde locale immédiate après modification ; envoi en ligne après environ une seconde si connecté.
- Vérification des données en ligne toutes les 15 secondes lorsque la page est visible, à son retour au premier plan et au rétablissement du réseau.
- Une saisie ou une fenêtre ouverte retarde l'affichage d'une version distante pour ne pas interrompre votre travail.
- Hors connexion, les changements restent sur l'appareil. En cas de modifications sur plusieurs appareils, aucun écrasement silencieux : exporter les versions puis choisir dans **Synchronisation**.
- **Garder cet appareil** remplace la version en ligne seulement si elle n'a pas encore changé entre-temps. **Utiliser la version en ligne** remplace la copie locale après sauvegarde.
- Les sauvegardes dans **Réglages → Restaurer la sauvegarde précédente** sont locales. L'export JSON permet une copie indépendante. Les données de l'ancienne version `startdeck.v1` ne sont pas supprimées.
- La déconnexion conserve les données sur cet appareil. Utiliser un profil de navigateur personnel ; un autre compte nécessite un autre profil.

## Mises à jour de la page

`sw.js` appartient désormais à StartDeck. Il ne met en cache que sa page pour le mode hors connexion, jamais les API privées. Il faut visiter le site en ligne au moins une fois pour préparer cette copie.

La page vérifie ses scripts et styles au démarrage, au retour au premier plan et chaque minute. Une mise à jour s'applique lorsque vous ne saisissez rien ; un bouton permet aussi de l'appliquer. Les changements HTML statiques seuls sont récupérés à la prochaine ouverture/recharge. Une nouvelle version de script ou de style ne demande pas d'incrémenter un numéro de cache.

La mise en ligne GitHub Pages peut prendre quelques minutes. Un appareil sans réseau conserve nécessairement la dernière version reçue. Les applications et onglets suspendus se resynchronisent à leur réouverture.

## Vérification après activation

Sur deux appareils connectés au même compte : créer une note sur A et vérifier son apparition sur B ; modifier hors ligne sur A puis reconnecter ; modifier la même copie séparément sur A et B pour vérifier l'écran de conflit. Vérifier qu'un utilisateur différent ne peut pas lire les données du premier compte. Les tests locaux simulent le réseau ; ils ne remplacent pas cette vérification avec votre projet réel.
