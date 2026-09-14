/* Step-5 renderer check, driven by a REAL validator payload.
 *
 *   node site/dashboard/population-verdict.test.js
 *
 * population.test.js covers step 1. This covers the other end: the plain-language
 * verdict copy reads a dozen nested fields off gaworld.group.validate output
 * (`by_key`, `heterogeneity_retained_ratio`, `discriminating_keys`, …). Rename
 * one of those in Python and every Python test stays green while the panel
 * throws and the user sees an empty card. The fixture below is verbatim output
 * from a real run, so it cannot drift into agreement with the renderer:
 *
 *   python -c "import json; \
 *     from gaworld.population.schema import normalize_spec; \
 *     from gaworld.population.generate import generate_population; \
 *     from gaworld.group.validate import run_validation, render_verdict; ..."
 *
 * It also pins the NaN fix: L2's `ratio` is null (not NaN) whenever the
 * reference signal sits under the noise floor. A bare NaN is not valid JSON and
 * made the browser discard the whole response.
 */
"use strict";

var VERDICT = {
  "verdict": {
    "population": 160,
    "days": 4,
    "baseline": {
      "seeds": [
        1,
        2
      ],
      "wasserstein1_by_key": {
        "emotion": 0.00827501522990503,
        "stress": 0.013232842052094318,
        "econ_security": 0.011973703647825741,
        "city_identity": 0.01018735621833226
      },
      "wasserstein1_max": 0.013232842052094318,
      "morans_i_by_key": {
        "emotion": 0.04696040906455893,
        "stress": 0.08087745167203478,
        "econ_security": 0.06465531958781608,
        "city_identity": 0.009970666581685895
      },
      "morans_i_sd_by_key": {
        "emotion": 0.011156005804656817,
        "stress": 0.02984275007684304,
        "econ_security": 0.0018114731515709442,
        "city_identity": 0.0032760214537742344
      },
      "run_seeds": [
        1,
        2
      ]
    },
    "layers": [
      {
        "layer": "L1",
        "name": "分布级：边缘分布距离是否落在参照层自身的种子间噪声量级内",
        "passed": true,
        "detail": {
          "gaps": {
            "emotion": {
              "wasserstein1": 0.01119793387100864,
              "ks": 0.06562499999999999,
              "mean_gap": -0.0019621513084304154,
              "sd_ratio": 0.9585274253938512
            },
            "stress": {
              "wasserstein1": 0.009129829961276894,
              "ks": 0.078125,
              "mean_gap": 0.0006738654063544458,
              "sd_ratio": 0.9639313585998259
            },
            "econ_security": {
              "wasserstein1": 0.010954926284407723,
              "ks": 0.04687500000000003,
              "mean_gap": 0.004580309188021131,
              "sd_ratio": 0.9556036482351005
            },
            "city_identity": {
              "wasserstein1": 0.011865932305053308,
              "ks": 0.06250000000000003,
              "mean_gap": -0.007557699642650462,
              "sd_ratio": 0.9744070416270756
            }
          },
          "budget": {
            "emotion": 0.01655003045981006,
            "stress": 0.026465684104188637,
            "econ_security": 0.023947407295651483,
            "city_identity": 0.02037471243666452
          },
          "failures": {},
          "seeds": 2
        },
        "note": "阈值 = 参照层跨种子 Wasserstein 均值 × 2.0（不是拍脑袋的绝对值）；跨 2 个种子取均值",
        "inconclusive": false,
        "status": "pass"
      },
      {
        "layer": "L2",
        "name": "网络级：邻居间的状态共变（Moran's I）是否落在参照层自身噪声量级内",
        "passed": true,
        "detail": {
          "by_key": {
            "emotion": {
              "reference_morans_i": 0.04696040906455893,
              "group_morans_i": 0.022577120525424425,
              "ratio": 0.08967341385752249,
              "ratio_spread": 0.0,
              "baseline_sd": 0.025,
              "z": 0.9753315415653802,
              "tolerance_z": 2.0,
              "usable": false,
              "usable_seeds": 1
            },
            "stress": {
              "reference_morans_i": 0.08087745167203478,
              "group_morans_i": 0.05897630610046574,
              "ratio": 0.6552961979485307,
              "ratio_spread": 0.2003039098147241,
              "baseline_sd": 0.02984275007684304,
              "z": 0.7338849641931486,
              "tolerance_z": 2.0,
              "usable": true,
              "usable_seeds": 2
            },
            "econ_security": {
              "reference_morans_i": 0.06465531958781608,
              "group_morans_i": 0.02357590109151389,
              "ratio": 0.38188046343373394,
              "ratio_spread": 0.615356796853875,
              "baseline_sd": 0.025,
              "z": 1.6431767398520873,
              "tolerance_z": 2.0,
              "usable": true,
              "usable_seeds": 2
            },
            "city_identity": {
              "reference_morans_i": 0.009970666581685895,
              "group_morans_i": -0.001240399232277211,
              "ratio": null,
              "ratio_spread": 0.0,
              "baseline_sd": 0.025,
              "z": 0.44844263255852423,
              "tolerance_z": 2.0,
              "usable": false,
              "usable_seeds": 0
            }
          },
          "failures": [],
          "worst_z": 1.6431767398520873,
          "tolerance_z": 2.0,
          "discriminating_keys": [
            "stress",
            "econ_security"
          ],
          "noise_floor": 0.05,
          "seeds": 2
        },
        "note": "判定 = |群体 I − 参照 I| ≤ 2.0 × 参照层跨种子标准差（与 L1 同一逻辑：阈值来自实测噪声，不是拍脑袋的比值上下界）；跨 2 个种子取均值",
        "inconclusive": false,
        "status": "pass"
      },
      {
        "layer": "L3",
        "name": "尾部与稀有事件：极端个体占比、分位区间宽度、首次越阈时间",
        "passed": true,
        "detail": {
          "by_key": {
            "emotion": {
              "reference": {
                "low_share": 0.0,
                "high_share": 0.05,
                "p10_p90_spread": 0.30317776449721245
              },
              "group": {
                "low_share": 0.0,
                "high_share": 0.028125,
                "p10_p90_spread": 0.3007336331174819
              },
              "spread_ratio": 0.9919382894593742
            },
            "stress": {
              "reference": {
                "low_share": 0.00625,
                "high_share": 0.04375,
                "p10_p90_spread": 0.3216631706726464
              },
              "group": {
                "low_share": 0.00625,
                "high_share": 0.03125,
                "p10_p90_spread": 0.30771701354921804
              },
              "spread_ratio": 0.9566435999052524
            },
            "econ_security": {
              "reference": {
                "low_share": 0.04375,
                "high_share": 0.03125,
                "p10_p90_spread": 0.4024023323942293
              },
              "group": {
                "low_share": 0.034375,
                "high_share": 0.025,
                "p10_p90_spread": 0.3821930050526864
              },
              "spread_ratio": 0.9497783046601628
            },
            "city_identity": {
              "reference": {
                "low_share": 0.046875,
                "high_share": 0.021875,
                "p10_p90_spread": 0.42053563550210726
              },
              "group": {
                "low_share": 0.053125,
                "high_share": 0.0125,
                "p10_p90_spread": 0.4109645059821867
              },
              "spread_ratio": 0.9772406219309027
            },
            "first_passage_stress_0.8": {
              "reference": {
                "crossing_rate": 0.0625,
                "median_first_passage_day": 1.0,
                "n_crossed": 10.0
              },
              "group": {
                "crossing_rate": 0.025,
                "median_first_passage_day": 1.0,
                "n_crossed": 4.0
              }
            }
          },
          "failures": [],
          "tolerance": 0.1,
          "seeds": 2
        },
        "note": "单列而非并入 L1：聚合近似的已知失效模式正是保住主体分布、压扁尾部",
        "inconclusive": false,
        "status": "pass"
      },
      {
        "layer": "L4",
        "name": "因果响应：同一政策冲击下的 ATE 方向、量级与子群异质性",
        "passed": true,
        "detail": {
          "outcome": "econ_security",
          "reference_ate": 0.0,
          "group_ate": 0.0,
          "same_sign": true,
          "magnitude_relative_error": 0.0,
          "reference_subgroup_effects": {
            "外省|employed": 0.0,
            "外省|other": 0.0,
            "本地|employed": 0.0,
            "本地|other": 0.0,
            "省内|employed": 0.0,
            "省内|other": 0.0
          },
          "group_subgroup_effects": {
            "外省|employed": 0.0,
            "外省|other": 0.0,
            "本地|employed": 0.0,
            "本地|other": 0.0,
            "省内|employed": 0.0,
            "省内|other": 0.0
          },
          "heterogeneity_retained_ratio": 1.0,
          "subgroup_sign_agreement": 1.0,
          "failures": [],
          "seeds": 2
        },
        "note": "最关键的一层：基线分布对齐但 ATE 反号的近似，用于政策研究会得出相反结论",
        "inconclusive": false,
        "status": "pass"
      }
    ],
    "gate_passed": true,
    "all_passed": true
  },
  "text": "═══ Group 模式验证门 ═══  人口 160｜4 天\n参照层跨种子基线（Wasserstein-1 最大）：0.0132｜配对实验种子：[1, 2]\n\n✅ 通过  L1  分布级：边缘分布距离是否落在参照层自身的种子间噪声量级内\n        注：阈值 = 参照层跨种子 Wasserstein 均值 × 2.0（不是拍脑袋的绝对值）；跨 2 个种子取均值\n        ✓ emotion          W1=0.0112（预算 0.0166）sd比=0.96\n        ✓ stress           W1=0.0091（预算 0.0265）sd比=0.96\n        ✓ econ_security    W1=0.0110（预算 0.0239）sd比=0.96\n        ✓ city_identity    W1=0.0119（预算 0.0204）sd比=0.97\n\n✅ 通过  L2  网络级：邻居间的状态共变（Moran's I）是否落在参照层自身噪声量级内\n        注：判定 = |群体 I − 参照 I| ≤ 2.0 × 参照层跨种子标准差（与 L1 同一逻辑：阈值来自实测噪声，不是拍脑袋的比值上下界）；跨 2 个种子取均值\n          emotion          参照 I=+0.047  群体 I=+0.023  （参照信号低于噪声地板，不参与判定）\n          stress           参照 I=+0.081  群体 I=+0.059  比=0.66 z=0.73（容差 2.0σ，σ=0.030）（跨种子波动 ±0.20）\n          econ_security    参照 I=+0.065  群体 I=+0.024  比=0.38 z=1.64（容差 2.0σ，σ=0.025）（跨种子波动 ±0.62）\n          city_identity    参照 I=+0.010  群体 I=-0.001  （参照信号低于噪声地板，不参与判定）\n\n✅ 通过  L3  尾部与稀有事件：极端个体占比、分位区间宽度、首次越阈时间\n        注：单列而非并入 L1：聚合近似的已知失效模式正是保住主体分布、压扁尾部\n          emotion          分位宽度比=0.99  低尾 0.000→0.000  高尾 0.050→0.028\n          stress           分位宽度比=0.96  低尾 0.006→0.006  高尾 0.044→0.031\n          econ_security    分位宽度比=0.95  低尾 0.044→0.034  高尾 0.031→0.025\n          city_identity    分位宽度比=0.98  低尾 0.047→0.053  高尾 0.022→0.013\n\n✅ 通过  L4  因果响应：同一政策冲击下的 ATE 方向、量级与子群异质性\n        注：最关键的一层：基线分布对齐但 ATE 反号的近似，用于政策研究会得出相反结论\n          ATE 参照=+0.0000  群体=+0.0000  同号=True  相对误差=0.0%\n          子群异质性保留=1.00  子群符号一致率=100%\n\n关口结论（L2 + L4 为分水岭）：✅ 通过\n全部四层：✅ 通过"
};

var PREVIEW = {
  "spec": {
    "size": 160,
    "seed": 7,
    "preset": "cn_county_town",
    "name": "generated_town",
    "demography": {
      "median_age": 36.0,
      "share_under_18": 0.16,
      "share_over_65": 0.14,
      "sex_ratio_m_per_100f": 104.0,
      "migrant_share": 0.38,
      "min_agent_age": 6
    },
    "household": {
      "mean_size": 2.6,
      "share_single_person": 0.25,
      "share_multigen": 0.18,
      "share_shared_rental": 0.12,
      "max_size": 6,
      "spouse_age_gap_mean": 2.0,
      "fertility_children_mean": 1.1
    },
    "education_work": {
      "tertiary_rate": 0.35,
      "employment_rate": 0.68,
      "unemployment_rate": 0.05,
      "gig_platform_share": 0.1,
      "industry_mix": {
        "tech": 0.18,
        "finance": 0.08,
        "medical": 0.07,
        "education": 0.09,
        "service": 0.38,
        "trade": 0.2
      }
    },
    "income": {
      "median_monthly": 6500.0,
      "gini": 0.42,
      "pareto_tail_alpha": 2.2,
      "tail_threshold_pct": 0.95
    },
    "geography": {
      "district_weights": {
        "余杭": 0.18000000000000002,
        "滨江": 0.12000000000000001,
        "西湖": 0.15000000000000002,
        "上城": 0.13000000000000003,
        "拱墅": 0.12000000000000001,
        "钱塘": 0.10000000000000002,
        "萧山": 0.12000000000000001,
        "临平": 0.08000000000000002
      }
    },
    "psychology": {
      "state_means": {
        "emotion": 0.58,
        "stress": 0.55,
        "econ_security": 0.52,
        "city_identity": 0.55,
        "policy_sensitivity": 0.5,
        "platform_dependence": 0.5,
        "risk_preference": 0.45,
        "voice_propensity": 0.45,
        "mobility_intent": 0.45
      },
      "state_sd": 0.12,
      "couple_states_to_attributes": true
    },
    "social_network": {
      "mean_degree": 12.0,
      "homophily_strength": 0.55,
      "geo_decay": 0.35,
      "rewire_p": 0.1,
      "workplace_size_alpha": 2.0,
      "dunbar_weak_cap": 150
    }
  },
  "issues": [],
  "has_errors": false,
  "bounds": {
    "household_mean_size": {
      "min": 1.75,
      "max": 4.75
    },
    "median_age": {
      "min": 26.257142857142856,
      "max": 59.857142857142854
    }
  }
};

var SCHEMA = {
  "version": "1.0",
  "presets": [
    "aging_community",
    "cn_county_town",
    "cn_tier1_district",
    "college_town",
    "custom",
    "us_suburb"
  ],
  "state_var_keys": [
    "emotion",
    "stress",
    "econ_security",
    "city_identity",
    "policy_sensitivity",
    "platform_dependence",
    "risk_preference",
    "voice_propensity",
    "mobility_intent"
  ],
  "industries": [
    "tech",
    "finance",
    "medical",
    "education",
    "service",
    "trade"
  ],
  "education_levels": [
    "小学及以下",
    "初中",
    "高中/中专",
    "大专",
    "本科",
    "硕士及以上"
  ],
  "hukou_labels": [
    "本地",
    "省内",
    "外省",
    "外国"
  ],
  "cohort_axes": [
    "age_band",
    "district",
    "employment",
    "gender",
    "hukou",
    "industry"
  ],
  "cohort_axis_labels": {
    "age_band": "年龄段 Age band",
    "industry": "行业 Industry",
    "hukou": "户籍 Hukou",
    "employment": "就业状态 Employment",
    "gender": "性别 Gender",
    "district": "居住区 District"
  },
  "labels": {
    "emotion": {
      "zh": "情绪",
      "en": "emotion"
    },
    "stress": {
      "zh": "压力",
      "en": "stress"
    },
    "econ_security": {
      "zh": "经济安全感",
      "en": "econ_security"
    },
    "city_identity": {
      "zh": "城市认同",
      "en": "city_identity"
    },
    "policy_sensitivity": {
      "zh": "政策敏感度",
      "en": "policy_sensitivity"
    },
    "platform_dependence": {
      "zh": "平台依赖",
      "en": "platform_dependence"
    },
    "risk_preference": {
      "zh": "风险偏好",
      "en": "risk_preference"
    },
    "voice_propensity": {
      "zh": "发声倾向",
      "en": "voice_propensity"
    },
    "mobility_intent": {
      "zh": "迁移意愿",
      "en": "mobility_intent"
    },
    "median_age": {
      "zh": "中位年龄",
      "en": "median_age"
    },
    "share_under_18": {
      "zh": "未成年人占比",
      "en": "share_under_18"
    },
    "share_over_65": {
      "zh": "65 岁以上占比",
      "en": "share_over_65"
    },
    "migrant_share": {
      "zh": "外地户籍占比",
      "en": "migrant_share"
    },
    "employment_rate": {
      "zh": "就业率",
      "en": "employment_rate"
    },
    "tertiary_rate": {
      "zh": "大专以上学历",
      "en": "tertiary_rate"
    },
    "income_median": {
      "zh": "月收入中位数",
      "en": "income_median"
    },
    "income_gini": {
      "zh": "收入差距（基尼）",
      "en": "income_gini"
    },
    "household_mean_size": {
      "zh": "户均人数",
      "en": "household_mean_size"
    },
    "share_single_person": {
      "zh": "独居家庭占比",
      "en": "share_single_person"
    },
    "share_multigen": {
      "zh": "三代同堂占比",
      "en": "share_multigen"
    },
    "share_shared_rental": {
      "zh": "合租家庭占比",
      "en": "share_shared_rental"
    },
    "mean_degree": {
      "zh": "人均社交关系数",
      "en": "mean_degree"
    },
    "population": {
      "zh": "居民数",
      "en": "population"
    },
    "cohorts": {
      "zh": "群体数",
      "en": "cohorts"
    },
    "group_llm_calls": {
      "zh": "实际模型调用",
      "en": "group_llm_calls"
    },
    "individual_agent_days": {
      "zh": "详细模拟人-天",
      "en": "individual_agent_days"
    },
    "savings_factor": {
      "zh": "成本对比",
      "en": "savings_factor"
    },
    "max_residual_l1": {
      "zh": "误差信号",
      "en": "max_residual_l1"
    },
    "L1": {
      "zh": "整体分布",
      "en": "L1 distributional"
    },
    "L2": {
      "zh": "邻里影响",
      "en": "L2 network"
    },
    "L3": {
      "zh": "边缘人群",
      "en": "L3 tails"
    },
    "L4": {
      "zh": "政策反应",
      "en": "L4 causal"
    }
  },
  "preset_descriptions": {
    "cn_county_town": {
      "title": "中国县城 / 普通城区",
      "summary": "最接近“平均”的一座小城：中位年龄 36 岁，就业率 68%，月收入中位数 6500 元，服务业和贸易占一半以上。",
      "use_when": "不确定选什么时就用它——它是其余预设的基准线。"
    },
    "cn_tier1_district": {
      "title": "一线城市城区",
      "summary": "年轻、高学历、互联网与金融密集：中位年龄 34 岁，高等教育率 52%，月收入中位数 11000 元，外来人口 55%，合租比例高。",
      "use_when": "想研究高流动性、高房租压力、平台经济相关的问题。"
    },
    "aging_community": {
      "title": "老龄化社区",
      "summary": "中位年龄 52 岁，65 岁以上占 34%，就业率仅 42%，医疗与服务业占比高，收入低且更平均。",
      "use_when": "想研究养老、医疗负担、代际同住、退休后社交收缩。"
    },
    "college_town": {
      "title": "大学城",
      "summary": "极年轻且高学历：中位年龄 27 岁，高等教育率 80%，教育行业占三分之一，45% 的人合租，收入低但差距小。",
      "use_when": "想研究青年群体、合租与流动、校园周边的信息传播。"
    },
    "us_suburb": {
      "title": "美国式郊区",
      "summary": "家庭为主：少儿占 23%，自有住房 72%，户均 2.5 人，外来人口少，但收入差距最大（基尼 0.48）。",
      "use_when": "想研究家庭结构、通勤、以及不平等较高的社区。"
    },
    "custom": {
      "title": "自定义",
      "summary": "从当前参数出发，任何一个旋钮被改动后都会自动切到这里。",
      "use_when": "你已经知道自己要什么。"
    }
  },
  "providers": [
    {
      "name": "ollama_local",
      "type": "ollama",
      "model": "gemma3n:e4b",
      "base_url": "http://localhost:11434/api/generate",
      "is_default": false
    },
    {
      "name": "ollama_gemma4",
      "type": "ollama",
      "model": "gemma4:e4b",
      "base_url": "http://localhost:11434/api/generate",
      "is_default": false
    },
    {
      "name": "ollama_qwen",
      "type": "ollama",
      "model": "qwen3.5:9b",
      "base_url": "http://localhost:11434/api/generate",
      "is_default": false
    },
    {
      "name": "omlx_qwen",
      "type": "openai",
      "model": "Qwen3.5-9B-MLX-4bit",
      "base_url": "http://127.0.0.1:8000/v1",
      "is_default": false
    },
    {
      "name": "openai_gpt",
      "type": "openai",
      "model": "gpt-5.4",
      "base_url": "https://api.openai.com/v1",
      "is_default": false
    },
    {
      "name": "minimax",
      "type": "anthropic",
      "model": "MiniMax-M2.7",
      "base_url": "https://api.minimaxi.com/anthropic",
      "is_default": true
    },
    {
      "name": "local_qwen4b",
      "type": "openai",
      "model": "qwen3-4b",
      "base_url": "http://127.0.0.1:8080/v1",
      "is_default": false
    }
  ],
  "defaults": {
    "size": 500,
    "seed": 42,
    "preset": "cn_county_town",
    "name": "generated_town",
    "demography": {
      "median_age": 36.0,
      "share_under_18": 0.16,
      "share_over_65": 0.14,
      "sex_ratio_m_per_100f": 104.0,
      "migrant_share": 0.38,
      "min_agent_age": 6
    },
    "household": {
      "mean_size": 2.6,
      "share_single_person": 0.25,
      "share_multigen": 0.18,
      "share_shared_rental": 0.12,
      "max_size": 6,
      "spouse_age_gap_mean": 2.0,
      "fertility_children_mean": 1.1
    },
    "education_work": {
      "tertiary_rate": 0.35,
      "employment_rate": 0.68,
      "unemployment_rate": 0.05,
      "gig_platform_share": 0.1,
      "industry_mix": {
        "tech": 0.18,
        "finance": 0.08,
        "medical": 0.07,
        "education": 0.09,
        "service": 0.38,
        "trade": 0.2
      }
    },
    "income": {
      "median_monthly": 6500.0,
      "gini": 0.42,
      "pareto_tail_alpha": 2.2,
      "tail_threshold_pct": 0.95
    },
    "geography": {
      "district_weights": {
        "余杭": 0.18000000000000002,
        "滨江": 0.12000000000000001,
        "西湖": 0.15000000000000002,
        "上城": 0.13000000000000003,
        "拱墅": 0.12000000000000001,
        "钱塘": 0.10000000000000002,
        "萧山": 0.12000000000000001,
        "临平": 0.08000000000000002
      }
    },
    "psychology": {
      "state_means": {
        "emotion": 0.58,
        "stress": 0.55,
        "econ_security": 0.52,
        "city_identity": 0.55,
        "policy_sensitivity": 0.5,
        "platform_dependence": 0.5,
        "risk_preference": 0.45,
        "voice_propensity": 0.45,
        "mobility_intent": 0.45
      },
      "state_sd": 0.12,
      "couple_states_to_attributes": true
    },
    "social_network": {
      "mean_degree": 12.0,
      "homophily_strength": 0.55,
      "geo_decay": 0.35,
      "rewire_p": 0.1,
      "workplace_size_alpha": 2.0,
      "dunbar_weak_cap": 150
    }
  },
  "ranges": {
    "size": {
      "min": 20,
      "max": 5000
    },
    "days": {
      "min": 1,
      "max": 90
    },
    "materialization_budget": {
      "min": 0,
      "max": 500
    },
    "audit_fraction": {
      "min": 0.0,
      "max": 0.25
    },
    "network_coupling": {
      "min": 0.0,
      "max": 2.0
    }
  },
  "notes": {
    "network_coupling": "群内零均值的社交图耦合项：cohort 层保留均值，社交图决定群内谁动得多。0 = 关闭（Phase 3 的 L2 未通过状态）。0.7 是针对验证门参照过程标定的，换成真实 LLM 个体层需重新标定。",
    "materialization_budget": "每天按完整个体保真度运行的人数。群体层几乎不花钱，总成本几乎完全由这个数决定。"
  }
};

var els = {};
function makeEl(id) {
  return { id: id, innerHTML: "", textContent: "", disabled: false, value: "", type: "", dataset: {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    addEventListener: function () {}, querySelector: function () { return null; },
    querySelectorAll: function () { return []; }, parentNode: { querySelector: function () { return null; } } };
}
global.document = { readyState: "complete",
  getElementById: function (id) { els[id] = els[id] || makeEl(id); return els[id]; },
  querySelectorAll: function () { return []; }, addEventListener: function () {} };
var realSetTimeout = global.setTimeout;
global.setTimeout = function (fn) { fn(); return 0; };
global.clearTimeout = function () {};
global.fetch = function (url) {
  var u = String(url), body;
  if (u.indexOf("/schema") >= 0) body = SCHEMA;
  else body = PREVIEW;
  return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(JSON.parse(JSON.stringify(body))); } });
};
/* The wizard draws its text through __()/__f() now, so supply the real zh-CN
   locale rather than a stub that echoes keys: the Chinese assertions below keep
   their meaning, and a typo'd key lands in missingKeys. */
var LOCALE = require(require("path").join(__dirname, "locales", "zh-CN.json"));
var missingKeys = [];
global.__ = function (key) {
  if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {
    missingKeys.push(key);
    return key;
  }
  return LOCALE[key];
};
global.__f = function (key, params) {
  var text = global.__(key);
  Object.keys(params || {}).forEach(function (name) {
    text = text.split("{" + name + "}").join(String(params[name]));
  });
  return text;
};

var mod = require(require("path").join(__dirname, "population.js"));

realSetTimeout(function () {
  var api = global.__POP_TEST__;
  if (!api) { process.stdout.write("FAIL: population.js did not expose a test hook\n"); process.exit(1); }
  api.setVerdict(VERDICT);
  api.setWritten([
    { key: "state_csv", label: "状态表 State CSV", hint: "每人一行", path: "output/population/x_state_init.csv",
      url: "/output/population/x_state_init.csv", bytes: 5482, preview: "id,name\n1,张三" },
  ]);
  api.setStep(5);
  api.render();
  var panel = els.popPanel.innerHTML;
  var checks = [
    ["step 5 renders without throwing", panel.length > 500],
    ["verdict headline present", panel.indexOf("这次群体模拟") >= 0],
    ["can/cannot checklist present", panel.indexOf("这次结果可以用来") >= 0 && panel.indexOf("不要用来") >= 0],
    ["L2 explained in plain words", panel.indexOf("关系好的人是否一起变化") >= 0],
    ["L2 direction diagnosed", panel.indexOf("传得太弱") >= 0 || panel.indexOf("传得过强") >= 0],
    ["L1 quotes a real number", /相差 0\.\d{3}/.test(panel)],
    ["L4 explains heterogeneity", panel.indexOf("谁受影响更大") >= 0],
    ["no undefined leaked into copy", panel.indexOf("undefined") < 0],
    ["no NaN leaked into copy", panel.indexOf("NaN") < 0],
    ["written file is a real link", panel.indexOf('href="/output/population/x_state_init.csv"') >= 0],
    ["written file has open + download", panel.indexOf("在新标签打开") >= 0 && panel.indexOf("download") >= 0],
    ["written file shows a preview", panel.indexOf("预览前几行") >= 0],
    ["bilingual label used", panel.indexOf("<em") >= 0],
    ["raw技术输出 still available", panel.indexOf("展开完整技术输出") >= 0],
    ["every locale key the wizard asks for exists",
      missingKeys.length === 0 || !process.stdout.write(
        "    missing: " + missingKeys.join(", ") + "\n")],
  ];
  var failed = 0;
  checks.forEach(function (c) { if (!c[1]) failed++; process.stdout.write((c[1] ? "  ok   " : "  FAIL ") + c[0] + "\n"); });
  if (failed) { process.stdout.write(failed + " check(s) failed\n"); process.exit(1); }
  process.stdout.write("population-verdict.test.js: all " + checks.length + " checks passed\n");
}, 0);
