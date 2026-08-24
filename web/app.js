// Configuración oficial completa de Firebase para HunterBot
const firebaseConfig = {
  apiKey: "AIzaSyDDMlrAtJzYkDe2pmq7CSaePiFb-Farluw",
  authDomain: "hunterbot-app.firebaseapp.com",
  projectId: "hunterbot-app",
  storageBucket: "hunterbot-app.firebasestorage.app",
  messagingSenderId: "40227128039",
  appId: "1:40227128039:web:75c07253fa458207561842"
};

// Inicializar Firebase
if (!firebase.apps.length) {
  firebase.initializeApp(firebaseConfig);
}
const db = firebase.firestore();

let allOpportunities = [];
let activeCategory = 'all';

// Cargar datos en tiempo real desde Firestore
function listenOpportunities() {
  db.collection("opportunities")
    .orderBy("score", "desc")
    .onSnapshot((snapshot) => {
      allOpportunities = [];
      snapshot.forEach((doc) => {
        allOpportunities.push({ id: doc.id, ...doc.data() });
      });

      console.log(`🔥 Oportunidades cargadas en vivo: ${allOpportunities.length}`);
      updateStats();
      renderCards();
    }, (error) => {
      console.error("Error conectando con Firestore:", error);
      loadMockData();
    });
}

function updateStats() {
  document.getElementById("stat-total").innerText = allOpportunities.length;
  document.getElementById("stat-real-estate").innerText = allOpportunities.filter(o => o.category === 'real_estate').length;
  document.getElementById("stat-boats").innerText = allOpportunities.filter(o => o.category === 'boat').length;

  if (allOpportunities.length > 0) {
    const avg = allOpportunities.reduce((acc, curr) => acc + (curr.score || 0), 0) / allOpportunities.length;
    document.getElementById("stat-avg-score").innerText = avg.toFixed(1);
  }
}

function filterCategory(cat) {
  activeCategory = cat;
  
  // Actualizar estilos de pestañas
  ['all', 'real_estate', 'boat', 'product'].forEach(c => {
    const el = document.getElementById(`tab-${c}`);
    if (el) {
      if (c === cat) {
        el.className = "px-4 py-2 rounded-xl text-sm font-medium bg-indigo-600 text-white shadow-lg shadow-indigo-600/30";
      } else {
        el.className = "px-4 py-2 rounded-xl text-sm font-medium bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700";
      }
    }
  });

  renderCards();
}

function renderCards() {
  const container = document.getElementById("grid-opportunities");
  const filtered = activeCategory === 'all' 
    ? allOpportunities 
    : allOpportunities.filter(o => o.category === activeCategory);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-16 text-center text-slate-500 bg-slate-800/20 border border-dashed border-slate-800 rounded-3xl">
        <i class="fa-solid fa-magnifying-glass text-4xl mb-3 text-slate-600"></i>
        <p class="text-lg font-medium text-slate-300">Esperando nuevas búsquedas</p>
        <p class="text-sm text-slate-500 mt-1">Escribe cualquier consulta en tu bot o en Antigravity para verla aquí en tiempo real.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(item => {
    const badgeColor = item.score >= 8.5 ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
      : item.score >= 7.0 ? "bg-blue-500/10 text-blue-400 border-blue-500/20" 
      : "bg-amber-500/10 text-amber-400 border-amber-500/20";

    const priceFmt = item.price > 0 ? `${new Intl.NumberFormat('es-ES').format(item.price)} €` : "Consultar precio";
    const m2Text = item.size_m2 ? `<span class="text-xs text-slate-400">(${item.size_m2} m²)</span>` : '';
    const lengthText = item.length_m ? `<span class="text-xs text-slate-400">(${item.length_m}m eslora)</span>` : '';

    const reasonsList = (item.reasons || []).slice(0, 2).map(r => `
      <li class="text-xs text-slate-400 flex items-center">
        <i class="fa-solid fa-check text-emerald-400 mr-2 text-[10px]"></i> ${r}
      </li>
    `).join('');

    return `
      <div class="bg-slate-800/60 border border-slate-700/60 rounded-2xl overflow-hidden hover:border-slate-600 transition-all flex flex-col justify-between hover:shadow-xl hover:shadow-indigo-500/5">
        <div class="p-5">
          <div class="flex items-center justify-between mb-3">
            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${badgeColor}">
              Score ${item.score ? item.score.toFixed(1) : '6.0'}/10
            </span>
            <span class="text-xs uppercase font-bold tracking-wider text-slate-400 bg-slate-900/60 px-2.5 py-1 rounded-lg">
              ${item.provider || 'HunterBot'}
            </span>
          </div>

          <h3 class="font-bold text-white text-base leading-snug mb-2 line-clamp-2" title="${item.title}">
            ${item.title}
          </h3>

          <div class="text-2xl font-black text-emerald-400 mb-3">
            ${priceFmt} ${m2Text} ${lengthText}
          </div>

          <div class="text-xs text-slate-400 flex items-center mb-4">
            <i class="fa-solid fa-location-dot mr-1.5 text-slate-500"></i>
            ${item.location || 'España'}
          </div>

          <ul class="space-y-1 bg-slate-900/40 p-3 rounded-xl border border-slate-800">
            ${reasonsList || '<li class="text-xs text-slate-500">Oportunidad evaluada y validada</li>'}
          </ul>
        </div>

        <div class="p-5 pt-0">
          <a href="${item.url}" target="_blank" class="w-full flex items-center justify-center space-x-2 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold rounded-xl transition shadow-lg shadow-indigo-600/20">
            <span>Ver Oferta Original</span>
            <i class="fa-solid fa-arrow-up-right-from-square text-xs"></i>
          </a>
        </div>
      </div>
    `;
  }).join('');
}

function loadMockData() {
  allOpportunities = [];
  updateStats();
  renderCards();
}

window.onload = listenOpportunities;
