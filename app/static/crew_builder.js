(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CrewBuilder = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ROLE_DEFS = {
    demolition: { title: "Мастер демонтажных работ", rate: 4800, specialty: "Демонтаж и подготовка помещений" },
    electrician: { title: "Электрик", rate: 5900, specialty: "Проводка, электроустановочные изделия и свет" },
    plumber: { title: "Сантехник", rate: 6100, specialty: "Разводка труб и установка сантехники" },
    climate: { title: "Монтажник инженерных систем", rate: 6200, specialty: "Вентиляция, отопление и климатическое оборудование" },
    waterproofing: { title: "Мастер по гидроизоляции", rate: 5000, specialty: "Гидроизоляция влажных зон" },
    floor_prep: { title: "Мастер по стяжке пола", rate: 5200, specialty: "Стяжка и выравнивание основания" },
    plasterer: { title: "Штукатур", rate: 5100, specialty: "Штукатурка и выравнивание стен" },
    drywall: { title: "Монтажник гипсокартона", rate: 5400, specialty: "Каркасы и листовые конструкции" },
    painter: { title: "Маляр-отделочник", rate: 4900, specialty: "Шпатлевание, грунтование, окраска и обои" },
    tiler: { title: "Плиточник", rate: 6000, specialty: "Облицовка стен и пола плиткой" },
    flooring: { title: "Мастер по напольным покрытиям", rate: 5500, specialty: "Ламинат, линолеум и плинтусы" },
    openings: { title: "Монтажник дверей и окон", rate: 5700, specialty: "Дверные и оконные блоки" },
    decorator: { title: "Мастер декоративной отделки", rate: 5300, specialty: "Панели, молдинги и финишный декор" },
    universal: { title: "Мастер-универсал", rate: 5000, specialty: "Прочие работы сметы" }
  };

  const WORK_TO_ROLE = {
    demolition: "demolition", electrical_wiring: "electrician", electrical_fittings: "electrician",
    lighting_install: "electrician", plumbing_rough: "plumber", plumbing_fixture_install: "plumber",
    ventilation_install: "climate", heating_climate_install: "climate", waterproofing: "waterproofing",
    floor_screed: "floor_prep", wall_plastering: "plasterer", drywall_install: "drywall",
    wall_putty: "painter", priming: "painter", wall_painting: "painter", wallpapering: "painter",
    tiling: "tiler", floor_covering_install: "flooring", door_window_install: "openings",
    decorative_finish_install: "decorator"
  };

  const WORK_LABELS = {
    demolition: "Демонтаж", electrical_wiring: "Электромонтаж", electrical_fittings: "Установка розеток и выключателей",
    lighting_install: "Монтаж освещения", plumbing_rough: "Разводка сантехники", plumbing_fixture_install: "Установка сантехники",
    ventilation_install: "Монтаж вентиляции", heating_climate_install: "Монтаж отопления и климата", waterproofing: "Гидроизоляция",
    floor_screed: "Стяжка пола", wall_plastering: "Штукатурные работы", drywall_install: "Монтаж гипсокартона",
    wall_putty: "Шпаклевание", priming: "Грунтование", wall_painting: "Покраска", wallpapering: "Поклейка обоев",
    tiling: "Укладка плитки", floor_covering_install: "Укладка напольного покрытия", door_window_install: "Монтаж дверей и окон",
    decorative_finish_install: "Декоративная отделка"
  };

  // Approximate square metres completed per person-day; deliberately simple demo assumptions.
  const PRODUCTIVITY = {
    demolition: 18, electrical_wiring: 12, plumbing_rough: 10, ventilation_install: 10,
    heating_climate_install: 10, waterproofing: 18, floor_screed: 16, wall_plastering: 14,
    drywall_install: 13, wall_putty: 20, priming: 35, wall_painting: 24, wallpapering: 20,
    tiling: 8, floor_covering_install: 20, door_window_install: 8, electrical_fittings: 18,
    plumbing_fixture_install: 8, lighting_install: 16, decorative_finish_install: 14
  };

  const NAMES = [
    "Алексей Морозов", "Дмитрий Соколов", "Михаил Кузнецов",
    "Андрей Волков", "Сергей Орлов", "Илья Новиков",
    "Максим Фёдоров", "Павел Смирнов", "Артём Васильев",
    "Николай Попов", "Евгений Лебедев", "Виктор Козлов",
    "Роман Павлов", "Антон Семёнов", "Владимир Голубев",
    "Константин Виноградов", "Денис Богданов", "Олег Воробьёв",
    "Виталий Фомин", "Кирилл Захаров", "Георгий Белов",
    "Александр Комаров", "Вадим Андреев", "Юрий Макаров",
    "Степан Никитин", "Глеб Тарасов", "Фёдор Баранов",
    "Борис Филиппов", "Ярослав Жуков", "Леонид Осипов",
    "Вячеслав Крылов", "Игорь Максимов", "Григорий Соловьёв",
    "Станислав Щербаков", "Валерий Ковалёв", "Пётр Ильин",
    "Аркадий Гусев", "Матвей Титов", "Тимофей Киселёв",
    "Даниил Куликов", "Семён Зайцев", "Василий Мельников"
  ];
  const EXPERIENCES = [7, 5, 9, 6, 8, 10, 4, 7];
  // The entry mode is explicit: a cached estimate must never decide which UI is shown.
  const state = { mode: "direct", estimate: null, roles: [], selected: {}, days: 1, selectionMessage: "" };
  const directState = { works: [], professions: [], selected: {}, minRate: "", maxRate: "", selectionMessage: "" };

  const candidatesFor = role => {
    const def = ROLE_DEFS[role] || ROLE_DEFS.universal;
    const offset = Object.keys(ROLE_DEFS).indexOf(role);
    return [0, 1, 2].map((n) => {
      const name = NAMES[(offset * 3 + n) % NAMES.length];
      const experience = EXPERIENCES[(offset * 2 + n) % EXPERIENCES.length];
      const factor = [0.94, 1, 1.08][n];
      return { id: `${role}-${n + 1}`, name, experience, role, roleTitle: def.title,
        specialty: def.specialty, rate: Math.round(def.rate * factor / 100) * 100 };
    });
  };

  const workEntries = estimate => {
    const result = [];
    (estimate?.rooms || []).forEach((roomEstimate, roomIndex) => {
      const room = roomEstimate.room || {};
      const works = room.works?.length ? room.works : (roomEstimate.items || []).map(i => ({ work_type: i.work_type, surface: i.surface }));
      const seen = new Set();
      works.forEach(raw => {
        const work = typeof raw === "string" ? { work_type: raw } : raw;
        const key = `${work.work_type}|${work.surface || ""}`;
        if (!work.work_type || seen.has(key)) return;
        seen.add(key);
        const floor = Number(roomEstimate.floor_area_m2) || Number(room.custom_floor_area) || Number(room.length_m) * Number(room.width_m) || 1;
        const walls = Number(roomEstimate.wall_area_m2) || Math.max(1, 2 * (Number(room.length_m) + Number(room.width_m)) * Number(room.height_m) - Number(room.openings_area_m2 || 0));
        const defaultWall = ["wall_plastering", "drywall_install", "wall_putty", "priming", "wall_painting", "wallpapering", "decorative_finish_install"].includes(work.work_type);
        const scope = work.surface === "wall" || work.surface === "ceiling" || (!work.surface && defaultWall) ? walls : floor;
        result.push({ ...work, roomIndex, scope: Math.max(1, scope), role: WORK_TO_ROLE[work.work_type] || "universal" });
      });
    });
    return result;
  };

  function deriveCrew(estimate) {
    const entries = workEntries(estimate);
    const byRole = {};
    entries.forEach(entry => {
      const role = entry.role;
      if (!byRole[role]) byRole[role] = { id: role, ...ROLE_DEFS[role] || ROLE_DEFS.universal, works: [], personDays: 0, scope: 0 };
      if (!byRole[role].works.includes(entry.work_type)) byRole[role].works.push(entry.work_type);
      byRole[role].scope += entry.scope;
      byRole[role].personDays += Math.max(0.5, entry.scope / (PRODUCTIVITY[entry.work_type] || 15));
    });
    return Object.values(byRole).map(role => ({ ...role, works: [...new Set(role.works)], personDays: Math.max(0.5, Math.round(role.personDays * 2) / 2) }));
  }

  const selectedFor = (role, selected) => {
    const value = selected[role.id];
    const list = Array.isArray(value) ? value : (value ? [value] : []);
    const available = new Set(candidatesFor(role.id).map(person => person.id));
    return list.filter((person, index) => person && available.has(person.id) && list.findIndex(item => item?.id === person.id) === index);
  };

  function toggleSpecialist(role, specialistId, selected) {
    const candidates = candidatesFor(role);
    const specialist = candidates.find(person => person.id === specialistId);
    if (!specialist) return { changed: false, reason: "Специалист недоступен." };
    const current = selectedFor({ id: role }, selected);
    const exists = current.some(person => person.id === specialistId);
    if (exists && current.length === 1) return { changed: false, reason: "Для каждой профессии нужен хотя бы один специалист." };
    selected[role] = exists ? current.filter(person => person.id !== specialistId) : [...current, specialist];
    return { changed: true, reason: "" };
  }

  function calculateCost(roles, selected, days) {
    const roleStats = roles.map(role => {
      const specialists = selectedFor(role, selected);
      const workerCount = specialists.length;
      const duration = workerCount ? Math.max(1, Math.ceil(role.personDays / workerCount)) : Infinity;
      const share = workerCount ? role.personDays / workerCount : 0;
      const cost = specialists.reduce((sum, specialist) => sum + share * specialist.rate, 0);
      return { role: role.id, specialists, workerCount, duration, cost };
    });
    const hasMissingRoles = roleStats.some(stat => !stat.workerCount);
    const baselineDays = hasMissingRoles ? Infinity : Math.max(1, roleStats.reduce((sum, stat) => sum + stat.duration, 0));
    const minimumDays = Math.max(1, roles.reduce((sum, role) => sum + Math.max(1, Math.ceil(role.personDays / Math.max(1, candidatesFor(role.id).length))), 0));
    const validDays = Number.isInteger(Number(days)) && Number(days) > 0;
    const desiredDays = validDays ? Number(days) : baselineDays;
    const urgency = validDays && Number.isFinite(baselineDays) && desiredDays < baselineDays ? Math.min(1.5, 1 + ((baselineDays - desiredDays) / baselineDays) * 0.75) : 1;
    const baseCost = roleStats.reduce((sum, stat) => sum + stat.cost, 0);
    const workerCount = roleStats.reduce((sum, stat) => sum + stat.workerCount, 0);
    const feasible = validDays && !hasMissingRoles && desiredDays >= baselineDays;
    const canAdd = roleStats.some(stat => stat.workerCount < candidatesFor(stat.role).length);
    return { baselineDays, minimumDays, desiredDays, urgency, baseCost: Math.round(baseCost / 100) * 100,
      total: Math.round(baseCost * urgency / 100) * 100, valid: validDays, feasible, canAdd, workerCount,
      impossible: validDays && desiredDays < minimumDays, hasMissingRoles, roleStats };
  }

  function setEstimate(estimate) {
    const nextRoles = deriveCrew(estimate);
    const relevant = new Set(nextRoles.map(r => r.id));
    Object.keys(state.selected).forEach(role => { if (!relevant.has(role)) delete state.selected[role]; });
    nextRoles.forEach(role => {
      const preserved = selectedFor(role, state.selected);
      state.selected[role.id] = preserved.length ? preserved : candidatesFor(role.id).slice(0, 1);
    });
    state.estimate = estimate; state.roles = nextRoles; state.selectionMessage = "";
    const timing = calculateCost(nextRoles, state.selected, state.days);
    if (!state.days || state.days === 1) state.days = timing.baselineDays;
    render();
  }

  const directRoleIds = direct => [...new Set([
    ...direct.works.map(work => WORK_TO_ROLE[work]).filter(Boolean),
    ...direct.professions.filter(role => ROLE_DEFS[role])
  ])];

  const directRoles = direct => directRoleIds(direct).map(id => ({ id, ...ROLE_DEFS[id] }));

  function addDirectChoice(kind, id, direct = directState) {
    const collection = kind === "work" ? direct.works : direct.professions;
    const valid = kind === "work" ? WORK_TO_ROLE[id] : ROLE_DEFS[id];
    if (!valid || collection.includes(id)) return false;
    collection.push(id);
    return true;
  }

  function removeDirectChoice(kind, id, direct = directState) {
    const collection = kind === "work" ? direct.works : direct.professions;
    const index = collection.indexOf(id);
    if (index < 0) return false;
    collection.splice(index, 1);
    const relevant = new Set(directRoleIds(direct));
    Object.keys(direct.selected).forEach(role => { if (!relevant.has(role)) delete direct.selected[role]; });
    return true;
  }

  function filterCandidates(role, minRate = "", maxRate = "") {
    const min = minRate === "" ? -Infinity : Number(minRate);
    const max = maxRate === "" ? Infinity : Number(maxRate);
    return candidatesFor(role).filter(person => (!Number.isFinite(min) || person.rate >= min) && (!Number.isFinite(max) || person.rate <= max));
  }

  function directSummary(direct = directState) {
    const relevant = new Set(directRoleIds(direct));
    const specialists = Object.entries(direct.selected)
      .filter(([role]) => relevant.has(role))
      .flatMap(([role, people]) => selectedFor({ id: role }, { [role]: people }));
    return { specialists, workerCount: specialists.length, dailyRate: specialists.reduce((sum, person) => sum + person.rate, 0) };
  }

  function toggleDirectSpecialist(role, specialistId, direct = directState) {
    if (!directRoleIds(direct).includes(role)) return { changed: false, reason: "Сначала добавьте профессию." };
    const specialist = candidatesFor(role).find(person => person.id === specialistId);
    if (!specialist) return { changed: false, reason: "Специалист недоступен." };
    const current = selectedFor({ id: role }, direct.selected);
    direct.selected[role] = current.some(person => person.id === specialistId)
      ? current.filter(person => person.id !== specialistId)
      : [...current, specialist];
    return { changed: true, reason: "" };
  }

  function enterDirect() { state.mode = "direct"; render(); }
  function enterEstimate() { state.mode = "estimate"; render(); }

  const money = value => Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽";
  const escapeHtml = value => String(value ?? "").replace(/[&<>\"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;" }[c]));
  const initials = name => name.split(" ").map(x => x[0]).join("");
  const workDescription = works => {
    const labels = [...new Set(works.map(work => WORK_LABELS[work] || "Другие работы"))];
    return labels.length > 3 ? "" : labels.join(", ");
  };

  function directCard(role, person) {
    const selected = selectedFor(role, directState.selected).some(item => item.id === person.id);
    return `<button data-direct-specialist="${person.id}" data-role="${role.id}" aria-pressed="${selected}" class="text-left p-4 rounded-xl border-2 transition-all ${selected ? "border-brand-red bg-red-50/40 shadow-sm" : "border-gray-100 hover:border-brand-blue"}"><div class="flex gap-3"><span class="w-11 h-11 shrink-0 rounded-full bg-gray-900 text-white grid place-items-center font-bold text-sm">${initials(person.name)}</span><span><b class="block text-sm">${escapeHtml(person.name)}</b><span class="block text-xs text-gray-500 mt-0.5">${person.experience} лет · ${money(person.rate)}/день</span></span></div><p class="text-xs text-gray-500 mt-3 min-h-[2rem]">${escapeHtml(person.specialty)}</p><span class="block mt-3 text-sm font-bold ${selected ? "text-brand-red" : "text-gray-700"}">${selected ? "Выбран ✓" : "Выбрать"}</span></button>`;
  }

  function renderDirect() {
    const box = document.getElementById("crew-builder");
    if (!box) return;
    const roles = directRoles(directState);
    const summary = directSummary(directState);
    const chips = [
      ...directState.works.map(id => ({ kind: "work", id, label: WORK_LABELS[id] })),
      ...directState.professions.map(id => ({ kind: "profession", id, label: ROLE_DEFS[id].title }))
    ].map(item => `<span class="pill ok inline-flex items-center gap-2">${escapeHtml(item.label)}<button data-remove-kind="${item.kind}" data-remove-id="${item.id}" class="font-bold" aria-label="Удалить ${escapeHtml(item.label)}">×</button></span>`).join("");
    const workOptions = Object.entries(WORK_LABELS).map(([id, label]) => `<option value="${id}" ${directState.works.includes(id) ? "disabled" : ""}>${escapeHtml(label)}</option>`).join("");
    const roleOptions = Object.entries(ROLE_DEFS).map(([id, def]) => `<option value="${id}" ${directState.professions.includes(id) ? "disabled" : ""}>${escapeHtml(def.title)}</option>`).join("");
    const sections = roles.map(role => {
      const visible = filterCandidates(role.id, directState.minRate, directState.maxRate);
      const hiddenSelected = selectedFor(role, directState.selected).filter(person => !visible.some(item => item.id === person.id)).length;
      return `<section class="border border-gray-200 rounded-2xl p-4 md:p-5"><div class="flex flex-wrap justify-between gap-2 mb-4"><div><h3 class="font-bold text-lg">${escapeHtml(role.title)}</h3><p class="text-xs text-gray-500 mt-1">${escapeHtml(role.specialty)}</p></div><div class="text-right text-xs"><b class="block text-brand-red">Выбрано: ${selectedFor(role, directState.selected).length}</b>${hiddenSelected ? `<span class="text-amber-700">Скрыто фильтром: ${hiddenSelected}</span>` : ""}</div></div>${visible.length ? `<div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">${visible.map(person => directCard(role, person)).join("")}</div>` : `<div class="rounded-xl bg-gray-50 p-6 text-center text-sm text-gray-500">Нет специалистов в выбранном диапазоне цен. Измените или сбросьте фильтр.</div>`}</section>`;
    }).join("");
    const people = summary.specialists.map(person => `<div class="flex justify-between gap-3 text-sm"><span><b class="block">${escapeHtml(person.name)}</b><span class="text-gray-400 text-xs">${escapeHtml(ROLE_DEFS[person.role].title)}</span></span><span class="text-gray-300 whitespace-nowrap">${money(person.rate)}/дн.</span></div>`).join("");
    box.innerHTML = `<div class="p-6 md:p-8 border-b bg-gray-50/50"><p class="text-xs font-bold uppercase tracking-wider text-brand-red">Вымышленные демонстрационные данные</p><h2 class="text-2xl md:text-3xl font-extrabold mt-1">Найдите специалиста для ремонта</h2><p class="text-sm text-gray-500 mt-2">Выберите нужный вид работ или профессию — мы покажем подходящих специалистов.</p><div class="grid md:grid-cols-2 gap-4 mt-6"><label class="text-sm font-semibold">Какую работу нужно выполнить?<select data-add-work class="block mt-2 w-full bg-white border border-gray-300 rounded-lg p-2.5"><option value="">Выберите вид работ</option>${workOptions}</select></label><label class="text-sm font-semibold">Какой специалист вам нужен?<select data-add-profession class="block mt-2 w-full bg-white border border-gray-300 rounded-lg p-2.5"><option value="">Выберите профессию</option>${roleOptions}</select></label></div>${chips ? `<div class="flex flex-wrap gap-2 mt-4">${chips}</div>` : ""}<div class="mt-5 pt-5 border-t border-gray-200"><p class="text-sm font-semibold">Стоимость работы в день</p><div class="flex flex-wrap items-end gap-3 mt-2"><label class="text-xs text-gray-500">От, ₽<input data-min-rate type="number" min="0" step="100" value="${escapeHtml(directState.minRate)}" class="block mt-1 w-32 bg-white border border-gray-300 rounded-lg px-3 py-2"></label><label class="text-xs text-gray-500">До, ₽<input data-max-rate type="number" min="0" step="100" value="${escapeHtml(directState.maxRate)}" class="block mt-1 w-32 bg-white border border-gray-300 rounded-lg px-3 py-2"></label><button data-reset-filter class="text-sm font-semibold text-brand-blue px-3 py-2">Сбросить фильтры</button></div></div></div><div class="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-6 p-6 md:p-8"><main>${directState.selectionMessage ? `<div class="mb-4 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl p-3">${escapeHtml(directState.selectionMessage)}</div>` : ""}${roles.length ? `<div class="grid gap-5">${sections}</div>` : `<div class="border border-dashed border-gray-300 rounded-2xl p-10 text-center text-gray-500">Выберите вид работ или специалиста, чтобы увидеть подходящие предложения.</div>`}</main><aside><div class="lg:sticky lg:top-24 bg-gray-900 text-white rounded-2xl p-5 md:p-6 shadow-xl"><h3 class="text-xl font-bold">Выбранные специалисты</h3><div class="mt-4 space-y-3">${people || `<p class="text-sm text-gray-400">Добавьте специалистов из подходящих профилей.</p>`}</div><dl class="border-t border-gray-700 mt-5 pt-5 space-y-2 text-sm"><div class="flex justify-between"><dt class="text-gray-400">Профессий</dt><dd>${roles.length}</dd></div><div class="flex justify-between"><dt class="text-gray-400">Всего специалистов</dt><dd>${summary.workerCount}</dd></div></dl><div class="border-t border-gray-700 mt-5 pt-5"><p class="text-sm font-semibold">Общая ставка бригады</p><p class="text-3xl font-extrabold mt-1 text-brand-yellow">${money(summary.dailyRate)}/день</p><p class="text-[11px] text-gray-500 mt-2">Без расчёта объёма, срока и полной стоимости ремонта.</p></div><p class="text-[11px] text-gray-500 mt-4 leading-relaxed">Профили и ставки вымышлены. Это не оферта и не предложение реальных подрядчиков.</p></div></aside></div>`;
    box.querySelector("[data-add-work]").onchange = event => { if (event.target.value) addDirectChoice("work", event.target.value); render(); };
    box.querySelector("[data-add-profession]").onchange = event => { if (event.target.value) addDirectChoice("profession", event.target.value); render(); };
    box.querySelectorAll("[data-remove-kind]").forEach(button => button.onclick = () => { removeDirectChoice(button.dataset.removeKind, button.dataset.removeId); render(); });
    box.querySelectorAll("[data-direct-specialist]").forEach(button => button.onclick = () => { const result = toggleDirectSpecialist(button.dataset.role, button.dataset.directSpecialist); directState.selectionMessage = result.reason; render(); });
    const updateRate = (key, event) => { directState[key] = event.target.value === "" ? "" : Number(event.target.value); render(); };
    box.querySelector("[data-min-rate]").onchange = event => updateRate("minRate", event);
    box.querySelector("[data-max-rate]").onchange = event => updateRate("maxRate", event);
    box.querySelector("[data-reset-filter]").onclick = () => { directState.minRate = ""; directState.maxRate = ""; render(); };
  }

  function render() {
    if (typeof document === "undefined") return;
    if (state.mode === "direct") renderDirect(); else renderEstimateMode();
  }

  function renderEstimateMode() {
    if (typeof document === "undefined") return;
    const box = document.getElementById("crew-builder");
    if (!box) return;
    if (!state.estimate) {
      box.innerHTML = `<div class="p-8 md:p-14 text-center"><div class="mx-auto w-16 h-16 rounded-2xl bg-red-50 text-brand-red grid place-items-center text-2xl font-extrabold">Б</div><h2 class="text-2xl font-bold mt-5">Сначала рассчитайте смету</h2><p class="text-gray-500 mt-2 max-w-xl mx-auto">После расчёта здесь появятся нужные специалисты, демонстрационные профили и предварительная стоимость работ.</p><button data-back-calc class="mt-6 bg-brand-red hover:bg-red-900 text-white font-semibold px-6 py-3 rounded-xl">Вернуться в калькулятор</button></div>`;
      box.querySelector("[data-back-calc]").onclick = () => globalThis.switchTab("calc"); return;
    }
    if (!state.roles.length) {
      box.innerHTML = `<div class="p-8 md:p-14 text-center"><h2 class="text-2xl font-bold">Для этой сметы специалисты не определены</h2><p class="text-gray-500 mt-2">Вернитесь в калькулятор и выберите хотя бы один вид работ.</p><button data-back-calc class="mt-6 bg-brand-red text-white font-semibold px-6 py-3 rounded-xl">Вернуться в калькулятор</button></div>`;
      box.querySelector("[data-back-calc]").onclick = () => globalThis.switchTab("calc"); return;
    }
    const price = calculateCost(state.roles, state.selected, state.days);
    const roleCards = state.roles.map(role => {
      const description = workDescription(role.works);
      const selected = selectedFor(role, state.selected);
      const duration = Math.max(1, Math.ceil(role.personDays / selected.length));
      return `<section class="border border-gray-200 rounded-2xl p-4 md:p-5"><div class="flex flex-wrap items-start justify-between gap-2 mb-4"><div><h3 class="font-bold text-lg">${escapeHtml(role.title)}</h3><p class="text-xs text-gray-500 mt-1">${description ? `${escapeHtml(description)} · ` : ""}≈ ${role.personDays} чел.-дн.</p></div><div class="text-right text-xs"><b class="block text-brand-red">Выбрано: ${selected.length} из ${candidatesFor(role.id).length}</b><span class="text-gray-500">≈ ${duration} раб. дн.</span></div></div><div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">${candidatesFor(role.id).map(person => { const isSelected = selected.some(item => item.id === person.id); return `<button data-specialist="${person.id}" data-role="${role.id}" aria-pressed="${isSelected}" class="text-left p-4 rounded-xl border-2 transition-all ${isSelected ? "border-brand-red bg-red-50/40 shadow-sm" : "border-gray-100 hover:border-brand-blue"}"><div class="flex gap-3"><span class="w-11 h-11 shrink-0 rounded-full bg-gray-900 text-white grid place-items-center font-bold text-sm">${initials(person.name)}</span><span><b class="block text-sm">${escapeHtml(person.name)}</b><span class="block text-xs text-gray-500 mt-0.5">${person.experience} лет · ${money(person.rate)}/день</span></span></div><p class="text-xs text-gray-500 mt-3 min-h-[2rem]">${escapeHtml(person.specialty)}</p><span class="block mt-3 text-sm font-bold ${isSelected ? "text-brand-red" : "text-gray-700"}">${isSelected ? "Выбран ✓" : "Выбрать"}</span></button>`; }).join("")}</div></section>`;
    }).join("");
    const deadlineNotice = !price.valid
      ? { text: "Укажите целое число дней больше нуля.", ok: false }
      : price.feasible
        ? { text: `Собранная бригада укладывается в желаемый срок. Расчётная длительность — около ${price.baselineDays} дн.`, ok: true }
        : price.impossible
          ? { text: `Даже максимальный состав в этой демонстрационной модели требует около ${price.minimumDays} дн. Гарантировать выбранный срок нельзя.`, ok: false }
          : { text: `Составу требуется около ${price.baselineDays} дн.${price.canAdd ? " Добавьте ещё специалиста в доступной профессии." : ""}`, ok: false };
    box.innerHTML = `<div class="p-6 md:p-8 border-b bg-gray-50/50"><div class="flex flex-wrap justify-between gap-4"><div><p class="text-xs font-bold uppercase tracking-wider text-brand-red">Демонстрационная функция</p><h2 class="text-2xl md:text-3xl font-extrabold mt-1">Бригада для вашего ремонта</h2><p class="text-sm text-gray-500 mt-2">Роли определены по работам текущей сметы. Все профили, ставки и сроки вымышлены.</p></div><button data-back-calc class="self-center border-2 border-brand-blue text-brand-blue font-semibold px-5 py-2.5 rounded-xl hover:bg-blue-50">← К калькулятору</button></div></div><div class="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-6 p-6 md:p-8"><main><div class="flex flex-wrap gap-2 mb-5">${state.roles.map(r => `<span class="pill ok">${escapeHtml(r.title)}</span>`).join("")}</div>${state.selectionMessage ? `<div class="mb-4 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl p-3">${escapeHtml(state.selectionMessage)}</div>` : ""}<div class="grid gap-5">${roleCards}</div></main><aside><div class="lg:sticky lg:top-24 bg-gray-900 text-white rounded-2xl p-5 md:p-6 shadow-xl"><h3 class="text-xl font-bold">Состав бригады</h3><div class="mt-4 space-y-3">${state.roles.flatMap(role => selectedFor(role, state.selected).map(person => `<div class="flex justify-between gap-3 text-sm"><span><b class="block">${escapeHtml(person.name)}</b><span class="text-gray-400 text-xs">${escapeHtml(role.title)}</span></span><span class="text-gray-300 whitespace-nowrap">${money(person.rate)}/дн.</span></div>`)).join("")}</div><div class="border-t border-gray-700 mt-5 pt-5"><label class="text-sm font-semibold" for="crew-days">Желаемый срок ремонта</label><div class="flex items-center gap-2 mt-2"><input id="crew-days" type="number" min="1" step="1" value="${escapeHtml(state.days)}" class="w-28 bg-white text-gray-900 border-2 border-transparent focus:border-brand-blue rounded-lg px-3 py-2 outline-none"><span class="text-sm text-gray-400">дней</span></div><div class="mt-3 text-xs rounded-lg p-3 ${deadlineNotice.ok ? "bg-green-900/60 text-green-100" : "bg-amber-900/60 text-amber-100"}">${escapeHtml(deadlineNotice.text)}</div><dl class="mt-5 space-y-2 text-sm"><div class="flex justify-between"><dt class="text-gray-400">Специалистов</dt><dd>${price.workerCount}</dd></div><div class="flex justify-between"><dt class="text-gray-400">Расчётный срок</dt><dd>${Number.isFinite(price.baselineDays) ? `${price.baselineDays} дн.` : "—"}</dd></div><div class="flex justify-between"><dt class="text-gray-400">Желаемый срок</dt><dd>${price.valid ? `${price.desiredDays} дн.` : "—"}</dd></div><div class="flex justify-between"><dt class="text-gray-400">Базовая стоимость</dt><dd>${money(price.baseCost)}</dd></div><div class="flex justify-between"><dt class="text-gray-400">Коэффициент срочности</dt><dd>× ${price.urgency.toFixed(2)}</dd></div></dl><div class="border-t border-gray-700 mt-5 pt-5"><p class="text-sm font-semibold text-white">Стоимость работ бригады</p><p class="text-3xl font-extrabold mt-1 text-brand-yellow">${price.valid ? money(price.total) : "—"}</p><p class="text-[11px] text-gray-500 mt-1">Предварительная демонстрационная оценка</p>${state.estimate.total != null ? `<div class="mt-4 pt-3 border-t border-gray-700 space-y-1 text-xs text-gray-400"><p>Материалы по смете: <span class="text-gray-200">${money(state.estimate.total)}</span></p>${price.valid ? `<p>Итого с материалами: <span class="font-semibold text-gray-200">${money(price.total + Number(state.estimate.total))}</span></p>` : ""}</div>` : ""}</div></div><p class="text-[11px] text-gray-500 mt-4 leading-relaxed">Срок — консервативная сумма длительностей профессий; параллельная работа этапов не гарантируется. Это не оферта и не предложение реальных подрядчиков.</p></div></aside></div>`;
    box.querySelectorAll("[data-back-calc]").forEach(b => b.onclick = () => globalThis.switchTab("calc"));
    box.querySelectorAll("[data-specialist]").forEach(b => b.onclick = () => { const result = toggleSpecialist(b.dataset.role, b.dataset.specialist, state.selected); state.selectionMessage = result.reason; render(); });
    box.querySelector("#crew-days").oninput = event => { state.days = event.target.value === "" ? "" : Number(event.target.value); render(); const input = box.querySelector("#crew-days"); input?.focus(); };
  }

  return { ROLE_DEFS, WORK_TO_ROLE, WORK_LABELS, PRODUCTIVITY, candidatesFor, selectedFor, toggleSpecialist, workDescription, workEntries, deriveCrew, calculateCost, setEstimate, directRoleIds, directRoles, addDirectChoice, removeDirectChoice, filterCandidates, directSummary, toggleDirectSpecialist, enterDirect, enterEstimate, render, state, directState };
});
