/* ==========================================================================
   Generational Evolution & Aging Engine — God's Town
   Time scale: 1 real day = 1 in-game year.
   Combat: Non-lethal. Death occurs ONLY via Old Age or Sickness.
   Traits & Genetics: Passed down across generations.
   ========================================================================== */

class GenerationEngine {
  constructor() {
    this.STORAGE_KEY = "gods_town_generations_v1";
    this.state = this.loadState();
  }

  getDefaultState() {
    return {
      genesisTimestamp: Date.now(),
      currentYear: 1,
      lineages: [
        {
          id: "lineage_sparta",
          familyName: "House of Westfall",
          bannerColor: "#2F4A3C",
          generationsCount: 1,
          characters: [
            { id: "c1", name: "Dakota I", age: 24, generation: 1, health: 100, sick: false, stats: { str: 80, spd: 75, def: 85, geneType: "Titan" }, lineageId: "lineage_sparta", history: ["Founded House of Westfall in Year 1"] },
            { id: "c2", name: "Sasha I", age: 22, generation: 1, health: 100, sick: false, stats: { str: 85, spd: 90, def: 70, geneType: "Berserker" }, lineageId: "lineage_sparta", history: ["Champion of the Northern Forest"] },
            { id: "c3", name: "Matt I", age: 26, generation: 1, health: 100, sick: false, stats: { str: 90, spd: 65, def: 95, geneType: "Guardian" }, lineageId: "lineage_sparta", history: ["Sheriff of the Old Guard"] }
          ]
        },
        {
          id: "lineage_pellegrin",
          familyName: "House of Pellegrin",
          bannerColor: "#D8B894",
          generationsCount: 1,
          characters: [
            { id: "c4", name: "Zoe I", age: 23, generation: 1, health: 100, sick: false, stats: { str: 70, spd: 95, def: 75, geneType: "Shadow" }, lineageId: "lineage_pellegrin", history: ["Master of Mirage Techniques"] },
            { id: "c5", name: "Dean I", age: 28, generation: 1, health: 100, sick: false, stats: { str: 75, spd: 80, def: 90, geneType: "Medic" }, lineageId: "lineage_pellegrin", history: ["Healer of the Valley"] },
            { id: "c6", name: "Piper I", age: 21, generation: 1, health: 100, sick: false, stats: { str: 82, spd: 88, def: 80, geneType: "Vanguard" }, lineageId: "lineage_pellegrin", history: ["Leader of the Eastern Patrol"] }
          ]
        }
      ],
      historyLog: ["Year 1: Genesis of God's Town 3v3 Evolutions League."]
    };
  }

  loadState() {
    try {
      const saved = localStorage.getItem(this.STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        this.updateTimeScale(parsed);
        return parsed;
      }
    } catch (e) {
      console.warn("Could not load generation state, using default:", e);
    }
    const state = this.getDefaultState();
    this.saveState(state);
    return state;
  }

  saveState(state = this.state) {
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      console.error("Failed to save generation state:", e);
    }
  }

  updateTimeScale(state) {
    const now = Date.now();
    const msPerDay = 86400000;
    const daysElapsed = Math.floor((now - state.genesisTimestamp) / msPerDay);
    const newYear = 1 + daysElapsed;

    if (newYear > state.currentYear) {
      const yearsPassed = newYear - state.currentYear;
      state.currentYear = newYear;
      this.advanceYears(state, yearsPassed);
    }
  }

  advanceYears(state, years) {
    state.lineages.forEach(lineage => {
      lineage.characters.forEach(char => {
        if (char.health <= 0) return; // already deceased

        char.age += years;

        // Random sickness chance (5% per year past age 30)
        if (char.age > 30 && !char.sick && Math.random() < 0.05 * years) {
          char.sick = true;
          char.history.push(`Contracted valley fever in Year ${state.currentYear}`);
          state.historyLog.push(`Year ${state.currentYear}: ${char.name} fell ill with valley fever.`);
        }

        // Mortality Check ONLY from Old Age (>75) or Severe Sickness
        const oldAgeThreshold = 75 + Math.floor(Math.random() * 20);
        const sicknessDeath = char.sick && Math.random() < 0.25;
        const naturalDeath = char.age >= oldAgeThreshold;

        if (naturalDeath || sicknessDeath) {
          char.health = 0;
          const cause = naturalDeath ? "old age" : "sickness";
          char.history.push(`Passed away from ${cause} at age ${char.age} in Year ${state.currentYear}`);
          state.historyLog.push(`Year ${state.currentYear}: ${char.name} passed away peacefully from ${cause} at age ${char.age}.`);

          // Spawn successor descendant with inherited genes!
          this.spawnDescendant(lineage, char, state);
        }
      });
    });
    this.saveState(state);
  }

  spawnDescendant(lineage, parent, state) {
    lineage.generationsCount += 1;
    const numToRoman = (n) => ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][n - 1] || `${n}`;
    const genRoman = numToRoman(lineage.generationsCount);

    // Genetic Trait Inheritance + Evolutionary Mutation (+/- 10%)
    const inherit = (val) => Math.min(100, Math.max(50, Math.round(val + (Math.random() * 20 - 8))));

    const child = {
      id: `c_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
      name: `${parent.name.split(' ')[0]} ${genRoman}`,
      age: 18,
      generation: lineage.generationsCount,
      health: 100,
      sick: false,
      stats: {
        str: inherit(parent.stats.str),
        spd: inherit(parent.stats.spd),
        def: inherit(parent.stats.def),
        geneType: `${parent.stats.geneType} Prime`
      },
      lineageId: lineage.id,
      history: [`Inherited genetic traits from ancestor ${parent.name} in Year ${state.currentYear}`]
    };

    lineage.characters.push(child);
    state.historyLog.push(`Year ${state.currentYear}: ${child.name} was born into ${lineage.familyName}, carrying forward the ${child.stats.geneType} lineage!`);
  }

  recordDecision(charId, decisionText, outcome) {
    this.state.lineages.forEach(lineage => {
      const char = lineage.characters.find(c => c.id === charId);
      if (char) {
        char.history.push(`Year ${this.state.currentYear}: ${decisionText} -> ${outcome}`);
        this.state.historyLog.push(`Year ${this.state.currentYear}: ${char.name} made the historical decision: "${decisionText}".`);
      }
    });
    this.saveState();
  }

  getActiveTeam(lineageId) {
    const lineage = this.state.lineages.find(l => l.id === lineageId) || this.state.lineages[0];
    const living = lineage.characters.filter(c => c.health > 0);
    return living.slice(-3); // top 3 living members
  }
}

if (typeof window !== "undefined") {
  window.GenerationEngine = GenerationEngine;
}
