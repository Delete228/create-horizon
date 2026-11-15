"""Native bounded mixing export must reject unsupported JSON instead of erasing it."""
import copy
import unittest

from reference_recipes import (
    burner_data_maps, closed_fluid_ingredient, closed_fluid_tags, compacting, dry_mixing, fluid_mixing,
    heated_mixing, loot_for_horizon, recipe_for_horizon, stock_closed_fluid_recipe,
)


class LootDialect(unittest.TestCase):
    def test_condition_discriminators_convert_without_changing_the_tree(self):
        legacy = {"type": "minecraft:item", "name": "create:white_sail", "conditions": [
            {"condition": "minecraft:inverted",
             "term": {"condition": "minecraft:block_state_property",
                      "block": "create:white_sail", "properties": {"facing": "up"}}},
            {"condition": "minecraft:survives_explosion"},
        ]}
        self.assertEqual(loot_for_horizon(legacy), {
            "type": "minecraft:item", "name": "create:white_sail", "conditions": [
                {"type": "minecraft:inverted",
                 "term": {"type": "minecraft:block_state_property",
                          "block": "create:white_sail", "properties": {"facing": "up"}}},
                {"type": "minecraft:survives_explosion"},
            ],
        })
        self.assertEqual(loot_for_horizon({"type": "minecraft:item",
                                          "condition": "minecraft:tool/can_silk_touch"}),
                         {"type": "minecraft:item", "condition": "minecraft:tool/can_silk_touch"})


class DryMixing(unittest.TestCase):
    def setUp(self):
        self.recipe = {'type': 'create:mixing', 'ingredients': [
            {'item': 'minecraft:andesite'}, {'tag': 'c:nuggets/iron'}],
            'results': [{'id': 'create:andesite_alloy'}]}

    def test_source_item_tag_and_alternative_forms(self):
        self.assertTrue(dry_mixing(self.recipe))
        self.recipe['ingredients'][0] = [{'item': 'minecraft:andesite'}, {'item': 'minecraft:stone'}]
        self.assertTrue(dry_mixing(self.recipe))
        self.recipe['results'][0].update(count=2, chance=.25, components={'minecraft:custom_data': {'marker': 1}})
        self.assertTrue(dry_mixing(self.recipe))

    def test_fluid_heat_and_unknown_ingredient_fields_fail_whole_recipe(self):
        for ingredient in [
            {'type': 'neoforge:single', 'fluid': 'minecraft:water', 'amount': 1000},
            {'item': 'minecraft:andesite', 'amount': 2},
            {'tag': 'c:nuggets/iron', 'unknown': 7},
            {'type': 'unported:ingredient', 'item': 'minecraft:andesite'},
            [], {}, 3,
        ]:
            with self.subTest(ingredient=ingredient):
                recipe = copy.deepcopy(self.recipe)
                recipe['ingredients'][0] = ingredient
                self.assertFalse(dry_mixing(recipe))
        for heat in ['heated', 'superheated', None, 1, 'unknown']:
            recipe = copy.deepcopy(self.recipe)
            recipe['heat_requirement'] = heat
            self.assertFalse(dry_mixing(recipe))
        for duration in [None, '100', .5, True, 1 << 31]:
            recipe = copy.deepcopy(self.recipe)
            recipe['processing_time'] = duration
            self.assertFalse(dry_mixing(recipe))

    def test_output_fluid_and_invalid_stack_numbers_are_not_flattened(self):
        for output in [
            {'fluid': 'minecraft:water', 'amount': 1000},
            {'id': 'create:andesite_alloy', 'amount': 1000},
            {'id': 'create:andesite_alloy', 'count': True},
            {'id': 'create:andesite_alloy', 'count': 0},
            {'id': 'create:andesite_alloy', 'count': 100},
            {'id': 'create:andesite_alloy', 'chance': float('nan')},
            {'id': 'create:andesite_alloy', 'chance': 1.01},
            {'id': 'create:andesite_alloy', 'components': []},
        ]:
            with self.subTest(output=output):
                recipe = copy.deepcopy(self.recipe)
                recipe['results'][0] = output
                self.assertFalse(dry_mixing(recipe))


class FluidMixing(unittest.TestCase):
    def setUp(self):
        self.recipe={'type':'create:mixing','ingredients':[
            {'tag':'c:flours/wheat'},
            {'type':'neoforge:single','fluid':'minecraft:water','amount':1000}],
            'results':[{'id':'create:dough'}]}

    def test_source_dough_and_actual_block_tag_mud_shape(self):
        self.assertTrue(fluid_mixing(self.recipe))
        self.recipe['ingredients'][0]={'type':'neoforge:block_tag','tag':'minecraft:convertable_to_mud'}
        self.recipe['ingredients'][1]['amount']=250
        self.recipe['results']=[{'id':'minecraft:mud'}]
        before=copy.deepcopy(self.recipe)
        self.assertTrue(fluid_mixing(self.recipe))
        self.assertEqual(self.recipe,before)

    def test_unknown_fluid_predicates_patch_and_amounts_are_rejected(self):
        for ingredient in [
            {'type':'neoforge:single','fluid':'test:unknown','amount':1000},
            {'type':'neoforge:single','fluid':'minecraft:water','amount':1000,'components':{}},
            {'type':'neoforge:tag','tag':'minecraft:water','amount':1000},
            {'type':'neoforge:single','fluid':'minecraft:water','amount':True},
            {'type':'neoforge:single','fluid':'minecraft:water','amount':0},
            {'type':'neoforge:single','fluid':'minecraft:water','amount':1<<31},
            {'type':'neoforge:block_tag','tag':'minecraft:convertable_to_mud','unknown':1},
        ]:
            with self.subTest(ingredient=ingredient):
                r=copy.deepcopy(self.recipe);r['ingredients'][1]=ingredient
                self.assertFalse(fluid_mixing(r))
        r=copy.deepcopy(self.recipe);r['heat_requirement']='heated'
        self.assertFalse(fluid_mixing(r))


class Compacting(unittest.TestCase):
    def test_nine_snow_blocks_and_stone_lava_keep_their_full_inputs(self):
        ice = {'type': 'create:compacting', 'ingredients': [{'item': 'minecraft:snow_block'}] * 9,
               'results': [{'id': 'minecraft:ice'}]}
        stone = {'type': 'create:compacting', 'ingredients': [
            {'item': 'minecraft:flint'}, {'item': 'minecraft:flint'}, {'item': 'minecraft:gravel'},
            {'type': 'neoforge:single', 'fluid': 'minecraft:lava', 'amount': 100}],
            'results': [{'id': 'minecraft:andesite'}]}
        for recipe in [ice, stone]:
            before = copy.deepcopy(recipe)
            self.assertTrue(compacting(recipe))
            self.assertEqual(recipe, before)
        self.assertFalse(compacting(dict(ice, type='create:mixing')))

    def test_fluid_tags_results_and_unknown_predicates_fail_closed(self):
        for ingredient in [
            {'type': 'neoforge:tag', 'tag': 'c:honey', 'amount': 1000},
            {'type': 'neoforge:single', 'fluid': 'create:chocolate', 'amount': 250},
            {'type': 'neoforge:single', 'fluid': 'minecraft:lava', 'amount': 100, 'components': {}},
            {'item': 'minecraft:flint', 'unknown_predicate': True},
        ]:
            recipe = {'type': 'create:compacting', 'ingredients': [ingredient],
                      'results': [{'id': 'minecraft:honey_block'}]}
            with self.subTest(ingredient=ingredient):
                self.assertFalse(compacting(recipe))
        self.assertFalse(compacting({'type': 'create:compacting', 'ingredients': ['minecraft:ice'],
                                    'results': [{'fluid': 'minecraft:water', 'amount': 1000}]}))


class StockClosedFluids(unittest.TestCase):
    def test_export_selects_five_pinned_ids_without_enabling_milk(self):
        for path in ('mixing/honey', 'mixing/chocolate_melting', 'compacting/honey',
                     'compacting/chocolate', 'emptying/honey_bottle'):
            kind = path.split('/')[0]
            with self.subTest(path=path):
                full = f'create/recipe/{path}.json'
                self.assertTrue(stock_closed_fluid_recipe(full, {'type': f'create:{kind}'}))
                self.assertFalse(stock_closed_fluid_recipe(full, {'type': 'create:crushing'}))
        self.assertFalse(stock_closed_fluid_recipe('create/recipe/mixing/chocolate.json',
                                                  {'type': 'create:mixing'}))
        self.assertFalse(stock_closed_fluid_recipe('create/recipe/emptying/builders_tea.json',
                                                  {'type': 'create:emptying'}))
        self.assertFalse(stock_closed_fluid_recipe('unknown.json', {'type': None}))

    def test_only_supported_closed_fluid_ingredients_match(self):
        self.assertTrue(closed_fluid_ingredient({'type': 'neoforge:tag', 'tag': 'c:honey', 'amount': 1000}))
        self.assertTrue(closed_fluid_ingredient({'type': 'neoforge:single', 'fluid': 'create:chocolate', 'amount': 250}))
        self.assertFalse(closed_fluid_ingredient({'type': 'neoforge:tag', 'tag': 'c:milk', 'amount': 250}))
        self.assertFalse(closed_fluid_ingredient({'type': 'neoforge:single', 'fluid': 'create:flowing_honey', 'amount': 250}))
        self.assertFalse(closed_fluid_ingredient({'type': 'neoforge:tag', 'tag': 'c:honey', 'amount': True}))
        self.assertFalse(closed_fluid_ingredient({'type': 'neoforge:single', 'fluid': 'create:honey', 'amount': 250, 'components': {}}))

    def test_tag_export_requires_pinned_source_but_omits_flowing_variants(self):
        paths = {f'c/tags/fluid/{fluid}.json': fluid for fluid in ('honey', 'chocolate')}
        source = {path: {'values': [f'create:flowing_{fluid}', f'create:{fluid}']}
                  for path, fluid in paths.items()}
        self.assertEqual(closed_fluid_tags(source.__getitem__), {
            path: {'replace': False, 'values': [f'create:{fluid}']} for path, fluid in paths.items()
        })
        with self.assertRaisesRegex(ValueError, 'Missing source fluid'):
            closed_fluid_tags(lambda path: {'values': ['create:flowing_honey']})


class ConditionalCrushing(unittest.TestCase):
    def test_only_exact_absent_ex_nihilo_branch_keeps_original_diorite(self):
        recipe = {'type': 'create:crushing', 'ingredients': [{'item': 'minecraft:diorite'}],
                  'processing_time': 350, 'results': [{'chance': .25, 'id': 'minecraft:quartz'}]}
        conditions = [{'type': 'neoforge:not',
                       'value': {'type': 'neoforge:mod_loaded', 'modid': 'exnihilosequentia'}}]
        source = dict(recipe, **{'neoforge:conditions': conditions})
        diorite = 'create/recipe/crushing/diorite.json'
        self.assertEqual(recipe_for_horizon(diorite, source), recipe)
        self.assertIn('neoforge:conditions', source)
        self.assertIsNone(recipe_for_horizon('create/recipe/crushing/granite.json', source))
        conditions[0]['value']['modid'] = 'unknown'
        self.assertIsNone(recipe_for_horizon(diorite, source))


class BurnerDataMaps(unittest.TestCase):
    def test_only_actual_source_files_are_exported(self):
        path='src/generated/resources/data/create/data_maps/item/superheated_blaze_burner_fuels.json'
        data={'values':{'create:blaze_cake':{'burn_time':3200}}}
        result=burner_data_maps([path],lambda name:copy.deepcopy(data))
        self.assertEqual(result,{'create/data_maps/item/superheated_blaze_burner_fuels.json':data})
        self.assertFalse(any('regular_' in name for name in result))
        self.assertEqual(burner_data_maps([],lambda name:self.fail('missing original file read')), {})

    def test_declared_regular_map_accepts_source_integer_or_object_only(self):
        path='src/generated/resources/data/create/data_maps/item/regular_blaze_burner_fuels.json'
        for value in [1,{'burn_time':1},(1<<31)-1]:
            self.assertTrue(burner_data_maps([path],lambda name:{'values':{'test:fuel':value}}))
        for value in [0,-1,True,1<<31,1.5,{'burn_time':3200,'unknown':1}, {'burn_time':None}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                burner_data_maps([path],lambda name:{'values':{'test:fuel':value}})


class HeatedMixing(unittest.TestCase):
    def test_source_brass_and_only_explicit_heat_levels(self):
        recipe={'type':'create:mixing','heat_requirement':'heated','ingredients':[
            {'tag':'c:ingots/copper'},{'tag':'c:ingots/zinc'}],
            'results':[{'id':'create:brass_ingot','count':2}]}
        before=copy.deepcopy(recipe)
        self.assertTrue(heated_mixing(recipe));self.assertEqual(recipe,before)
        recipe['heat_requirement']='superheated';self.assertTrue(heated_mixing(recipe))
        for value in ['none','unknown',None,1,True]:
            recipe['heat_requirement']=value;self.assertFalse(heated_mixing(recipe))
        recipe['heat_requirement']='heated'
        recipe['ingredients'].append({'type':'neoforge:single','fluid':'minecraft:water','amount':1000})
        self.assertFalse(heated_mixing(recipe))


if __name__ == '__main__':
    unittest.main()
